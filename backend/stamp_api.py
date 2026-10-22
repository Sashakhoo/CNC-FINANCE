"""
Document Centre API - upload a PDF, place the company chop / signature /
text, export a flattened stamped PDF, and verify it later by SHA-256.

Roles (enforced here, never just hidden in the UI):
  director : everything - stamps, settings, all documents, audit trail, void
  admin    : upload + stamp + export, own documents          (spec: STAMPER)
  viewer   : read completed documents, verify                (spec: VIEWER)

This is a company document-stamping and integrity-check tool. Wording is
deliberately "registered by CODE N CODE SOLUTION" - it is not a government
stamp, an SSM/LHDN verification, or a certificate-authority signature.
"""
import io
import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from PIL import Image

import auth
import storage
import stamp_files
import stamp_pdf
import stamp_store
from stamp_pdf import StampError

router = APIRouter(prefix="/api")

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stamp_assets")
DOC_ID_RE = re.compile(r"^CNC-\d{8}-[A-Z0-9]{6}$")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_ITEMS = 200
MAX_PLACEMENTS = 3000
TEXT_COLORS = {"blue": "#16168a", "red": "#c0261b", "green": "#1a7f37", "black": "#15141a"}
CATEGORIES = ["company", "approval", "status", "custom"]


# --- request helpers -----------------------------------------------------

def _ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def _ua(request: Request) -> str:
    return request.headers.get("user-agent", "")


def _audit(request: Request, event: str, user: dict = None, document_id: str = None, **meta):
    try:
        stamp_store.audit(event, user=user, document_id=document_id, ip=_ip(request),
                          user_agent=_ua(request), metadata=meta)
    except Exception as exc:          # an audit hiccup must never break the action itself
        print(f"stamp audit failed: {exc}")


def same_origin(request: Request):
    """CSRF guard for cookie-authenticated writes: a browser always sends
    Origin on cross-site POST/PUT/DELETE, so a mismatch is refused."""
    origin = request.headers.get("origin")
    if origin:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        if urlparse(origin).netloc.lower() != host.lower():
            raise HTTPException(status_code=403, detail="Cross-site request refused")


def require_stamp(request: Request) -> dict:
    user = auth.require_auth(request)
    if not auth.can(user["role"], "stamp"):
        raise HTTPException(status_code=403, detail="Your account can't stamp documents")
    return user


def require_stamp_admin(request: Request) -> dict:
    user = auth.require_auth(request)
    if not auth.can(user["role"], "stamp_admin"):
        raise HTTPException(status_code=403, detail="Only a director can do this")
    return user


def _is_admin(user: dict) -> bool:
    return auth.can(user["role"], "stamp_admin")


async def _body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail=f"File is larger than the {limit // (1024 * 1024)} MB limit.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail=f"File is larger than the {limit // (1024 * 1024)} MB limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def _fail(e: StampError):
    raise HTTPException(status_code=e.status, detail=e.message)


def _max_upload_bytes() -> int:
    env_cap = int(os.environ.get("MAX_UPLOAD_MB", "50") or 50)
    mb = max(1, min(int(stamp_store.get_settings().get("max_upload_mb") or 20), env_cap))
    return mb * 1024 * 1024


def _clean_filename(name: str) -> str:
    """Kept for display only - never used as a storage path."""
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    name = re.sub(r"[\x00-\x1f\x7f<>:\"|?*]", "", name)[:150]
    if not name.lower().endswith(".pdf"):
        name = (name or "document") + ".pdf"
    return name


def _png(data: bytes) -> bytes:
    """Decode and re-encode every uploaded image. Whatever was uploaded, what
    gets stored is a plain PNG we produced ourselves."""
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image is larger than 5 MB.")
    try:
        Image.open(io.BytesIO(data)).verify()
        img = Image.open(io.BytesIO(data))
        if img.format not in ("PNG", "JPEG", "WEBP"):
            raise ValueError
        img = img.convert("RGBA")
        if img.width < 8 or img.height < 8:
            raise ValueError
        img.thumbnail((1600, 1600), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, "PNG", optimize=True)
        return out.getvalue()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Upload a PNG image (transparent background works best).")


# --- startup seed ----------------------------------------------------------

def seed_defaults():
    """First run only: the official company chop (shipped in the image at
    backend/stamp_assets/, copied into storage) and the standard text stamps.
    A director can replace the chop image later from Manage Stamps."""
    if stamp_store.stamp_count() > 0:
        return
    chop = os.path.join(ASSET_DIR, "company_chop.png")
    if os.path.isfile(chop):
        with open(chop, "rb") as f:
            key = stamp_files.get_storage().put(f.read(), "png")
        stamp_store.create_stamp(name="Company Chop", category="company", kind="image",
                                 file_key=key, mime_type="image/png", is_default=True)
    for name, color, cat in (("APPROVED", "#1a7f37", "approval"), ("CERTIFIED", "#16168a", "approval"),
                             ("RECEIVED", "#16168a", "status"), ("PAID", "#c0261b", "status")):
        stamp_store.create_stamp(name=name.title(), category=cat, kind="text", text=name, color=color)


# --- views of a document ---------------------------------------------------

def _doc_view(d: dict, user: dict) -> dict:
    out = {k: d.get(k) for k in (
        "document_id", "original_filename", "status", "page_count", "file_size", "final_size",
        "original_sha256", "final_sha256", "version", "created_by_name", "created_at",
        "completed_at", "voided_at", "void_reason", "summary")}
    sg = stamp_store.get_signing(d["document_id"])
    out_for_signature = bool(sg and sg["status"] == "OPEN")
    out["can_edit"] = d["status"] in ("DRAFT", "FAILED") and not out_for_signature and (
        d["created_by"] == user["id"] or _is_admin(user)) and auth.can(user["role"], "stamp")
    if sg and sg["status"] != "CANCELLED":
        reqs = [r for r in stamp_store.list_sign_requests(d["document_id"]) if r["status"] != "CANCELLED"]
        out["signing"] = {"status": sg["status"], "total": len(reqs),
                          "signed": sum(1 for r in reqs if r["status"] == "SIGNED"),
                          "declined": sum(1 for r in reqs if r["status"] == "DECLINED")}
    out["can_void"] = d["status"] == "COMPLETED" and _is_admin(user)
    return out


def _get_doc(document_id: str, user: dict, *, edit: bool = False) -> dict:
    if not DOC_ID_RE.match(document_id or ""):
        raise HTTPException(status_code=404, detail="Document not found")
    d = stamp_store.get_document(document_id)
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    if _is_admin(user):
        return d
    if d["created_by"] == user["id"] and auth.can(user["role"], "stamp"):
        return d
    if not edit and user["role"] == "viewer" and d["status"] in ("COMPLETED", "VOID"):
        return d
    raise HTTPException(status_code=403, detail="You do not have permission to open this document")


def _usable_stamps(user: dict) -> list:
    return [s for s in stamp_store.list_stamps() if user["role"] in s["allowed_roles"] or _is_admin(user)]


def _server_dates() -> dict:
    s = stamp_store.get_settings()
    now = datetime.now(stamp_store.get_tz(s.get("timezone")))
    out = {}
    for fmt in stamp_pdf.DATE_FORMATS:
        out[fmt] = stamp_pdf.format_date(now, fmt)
        out[fmt + "|time"] = stamp_pdf.format_date(now, fmt, True)
    return out


# --- overview / config -----------------------------------------------------

@router.get("/stamp/overview")
def overview(request: Request):
    user = auth.require_auth(request)
    admin = _is_admin(user)
    if admin:
        docs = stamp_store.list_documents(limit=8)
    elif user["role"] == "viewer":
        docs = stamp_store.list_documents(completed_only=True, limit=8)
    else:
        docs = stamp_store.list_documents(owner_id=user["id"], limit=8)
    return {
        "stats": stamp_store.stats(),
        "recent": [_doc_view(d, user) for d in docs],
        "activity": stamp_store.list_audit(limit=10) if admin else [],
        "verifications": stamp_store.list_verifications(8) if admin else [],
    }


@router.get("/stamp/config")
def config(request: Request):
    user = auth.require_auth(request)
    s = stamp_store.get_settings()
    return {
        "user": {"username": user["username"], "role": user["role"],
                 "can_stamp": auth.can(user["role"], "stamp"), "is_admin": _is_admin(user)},
        "settings": s,
        "stamps": _usable_stamps(user) if auth.can(user["role"], "stamp") else [],
        "signatures": stamp_store.list_signatures(user["id"]) if auth.can(user["role"], "stamp") else [],
        "fonts": list(stamp_pdf.FONTS), "shapes": list(stamp_pdf.SHAPES),
        "text_presets": stamp_store.TEXT_PRESETS,
        "text_colors": TEXT_COLORS,
        "date_formats": stamp_pdf.DATE_FORMATS,
        "server_dates": _server_dates(),
        "max_upload_mb": _max_upload_bytes() // (1024 * 1024),
        "categories": CATEGORIES,
        "users": [u["username"] for u in storage.list_users()] if _is_admin(user) else [],
    }


# --- documents -------------------------------------------------------------

@router.post("/stamp/documents", dependencies=[Depends(same_origin)])
async def upload_document(request: Request, filename: str = "document.pdf"):
    user = require_stamp(request)
    data = await _body(request, _max_upload_bytes())
    try:
        reader = stamp_pdf.open_pdf(data, _max_upload_bytes())
    except StampError as e:
        _fail(e)
    key = stamp_files.get_storage().put(data, "pdf")      # the original is stored exactly as uploaded
    local = datetime.now(stamp_store.get_tz(stamp_store.get_settings().get("timezone")))
    doc = stamp_store.create_document(
        original_filename=_clean_filename(filename), original_file_key=key,
        original_sha256=stamp_pdf.sha256_hex(data), file_size=len(data),
        page_count=len(reader.pages), user=user, id_date=local.strftime("%Y%m%d"))
    _audit(request, "DOCUMENT_UPLOADED", user, doc["document_id"],
           filename=doc["original_filename"], size=len(data), pages=doc["page_count"])
    return _doc_view(doc, user)


@router.get("/stamp/documents")
def list_documents(request: Request, q: str = None, status: str = None, user: str = None,
                   date_from: str = None, date_to: str = None):
    me = auth.require_auth(request)
    for d in (date_from, date_to):
        if d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            raise HTTPException(status_code=422, detail="Dates must be YYYY-MM-DD")
    if status and status not in ("DRAFT", "PROCESSING", "COMPLETED", "FAILED", "VOID"):
        raise HTTPException(status_code=422, detail="Unknown status")
    kw = dict(q=q, status=status, date_from=date_from, date_to=date_to)
    if _is_admin(me):
        docs = stamp_store.list_documents(user=user, **kw)
    elif me["role"] == "viewer":
        docs = stamp_store.list_documents(completed_only=True, user=user, **kw)
    else:
        docs = stamp_store.list_documents(owner_id=me["id"], **kw)
    return [_doc_view(d, me) for d in docs]


@router.get("/stamp/documents/{document_id}")
def get_document(document_id: str, request: Request):
    user = auth.require_auth(request)
    d = _get_doc(document_id, user)
    out = _doc_view(d, user)
    out["draft"] = d.get("draft") if out["can_edit"] else None
    if d["status"] in ("DRAFT", "FAILED"):
        try:
            reader = stamp_pdf.open_pdf(stamp_files.get_storage().get(d["original_file_key"]))
            out["pages"] = stamp_pdf.page_sizes(reader)
            out["fields"] = stamp_pdf.form_fields(reader) if out["can_edit"] else []
        except (StampError, stamp_files.StorageError):
            out["pages"], out["fields"] = [], []
    if _is_admin(user) or d["created_by"] == user["id"]:
        out["signing_detail"] = _signing_view(d["document_id"])
    return out


@router.get("/stamp/documents/{document_id}/file")
def document_file(document_id: str, request: Request, which: str = "original"):
    """Inline bytes for the on-screen preview (not the download - that is /download)."""
    user = auth.require_auth(request)
    d = _get_doc(document_id, user)
    key = d["final_file_key"] if which == "final" else d["original_file_key"]
    if which == "original" and user["role"] == "viewer":
        raise HTTPException(status_code=403, detail="You do not have permission to open this document")
    if not key:
        raise HTTPException(status_code=404, detail="File not available")
    try:
        data = stamp_files.get_storage().get(key)
    except stamp_files.StorageError:
        raise HTTPException(status_code=404, detail="File not available")
    return Response(content=data, media_type="application/pdf",
                    headers={"Cache-Control": "private, no-store", "Content-Disposition": "inline"})


HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
URL_RE = re.compile(r"^(https?://|mailto:)[^\s<>\"']{1,500}$", re.I)
SIGNER_FIELDS = ("signature", "initials", "text", "date")
MAX_SIGNERS = 10


class Item(BaseModel):
    # stamp | signature | image | text (stamp-style) | date | plain (free text) | shape | ink
    # | link | signer (a box for someone else to fill)
    kind: str
    stamp_id: int | None = None
    sig_id: int | None = None
    image_id: int | None = None
    text: str | None = None
    color: str | None = None
    border: bool = True
    font: str | None = None
    bold: bool = False
    italic: bool = False
    fs: float | None = None
    shape: str | None = None
    stroke: str | None = None
    fill: str | None = None
    sw: float | None = None
    points: list[list[float]] | None = None
    url: str | None = None
    signer_name: str | None = None
    signer_contact: str | None = None
    field: str | None = None
    pages: str = "current"
    page: int = 1
    x: float
    y: float
    w: float
    h: float
    rotation: float = 0
    opacity: float = 1
    date_format: str | None = None
    with_time: bool = False


class Draft(BaseModel):
    items: list[Item] = []
    fields: dict[str, str] = {}       # existing PDF form fields: name -> value


def _not_out_for_signature(document_id: str):
    sg = stamp_store.get_signing(document_id)
    if sg and sg["status"] == "OPEN":
        raise HTTPException(status_code=409, detail="This document is out for signature. "
                                                    "Cancel the request to edit it again.")


@router.put("/stamp/documents/{document_id}/draft", dependencies=[Depends(same_origin)])
def save_draft(document_id: str, body: Draft, request: Request):
    user = require_stamp(request)
    d = _get_doc(document_id, user, edit=True)
    if d["status"] not in ("DRAFT", "FAILED"):
        raise HTTPException(status_code=409, detail="This document has already been stamped")
    _not_out_for_signature(document_id)
    if len(body.items) > MAX_ITEMS:
        raise HTTPException(status_code=422, detail="Too many items on this document")
    stamp_store.save_draft(document_id, {"items": [i.model_dump(exclude_none=True) for i in body.items],
                                         "fields": body.fields})
    return {"ok": True}


def _clean_text(text: str, limit: int, multiline: bool = False) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if multiline:
        text = "\n".join(line.rstrip() for line in text.split("\n")).strip("\n")
    else:
        text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        raise StampError(f"Text is too long (limit {limit} characters).")
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        raise StampError("Text can only use standard Latin letters, numbers and punctuation.")
    return text


def _color(value, default):
    return value if value and HEX_RE.match(value) else default


def _resolve(body: Draft, d: dict, user: dict, *, allow_signers: bool = False) -> dict:
    """Turn what the editor sent into concrete, authorised, per-page
    placements. Nothing from the browser is trusted: stamp text and images
    come from the database, signatures are the caller's own, document images
    belong to this document, and dates come from the server clock.
    Returns {placements, image_keys, labels, links, fields, signers, now}."""
    settings = stamp_store.get_settings()
    now = datetime.now(stamp_store.get_tz(settings.get("timezone")))
    usable = {s["id"]: s for s in _usable_stamps(user)}
    image_keys, placements, labels, links, signers = {}, [], [], [], []
    items = body.items

    if len(items) > MAX_ITEMS:
        raise StampError("Too many items on this document.")

    for it in items:
        for v in (it.x, it.y, it.w, it.h, it.rotation, it.opacity):
            if v != v or v in (float("inf"), float("-inf")):
                raise StampError("Invalid stamp position.")
        if not (0.001 <= it.w <= 2 and 0.001 <= it.h <= 2 and -1 <= it.x <= 1.5 and -1 <= it.y <= 1.5):
            raise StampError("Invalid stamp position.")
        base = {"x": it.x, "y": it.y, "w": it.w, "h": it.h,
                "rotation": float(it.rotation) % 360, "opacity": max(0.05, min(1.0, it.opacity))}
        pages = stamp_pdf.parse_pages(it.pages, d["page_count"], it.page)
        if it.kind == "stamp":
            s = usable.get(it.stamp_id)
            if not s:
                raise StampError("You do not have permission to use this stamp.", 403)
            row = stamp_store.get_stamp_row(s["id"])
            base["stamp_id"] = s["id"]
            if s["kind"] == "image":
                key = f"stamp{s['id']}"
                image_keys[key] = row["file_key"]
                base.update(kind="image", image=key)
            else:
                base.update(kind="text", text=row["text"], color=row["color"], border=True)
            labels.append(s["name"])
        elif it.kind == "signature":
            sig = (stamp_store.get_own_signature(user["id"], it.sig_id) if it.sig_id
                   else stamp_store.get_signature(user["id"]))
            if not sig:
                raise StampError("That signature is no longer available. Choose or create a signature again.")
            key = f"sig{sig['id']}"
            image_keys[key] = sig["file_key"]
            base.update(kind="image", image=key, signature_id=sig["id"])
            labels.append("Initials" if sig.get("kind") == "initials" else "Signature")
        elif it.kind == "image":
            img = stamp_store.get_doc_image(d["document_id"], it.image_id or 0)
            if not img:
                raise StampError("An image on this document is missing. Add it again.")
            key = f"img{img['id']}"
            image_keys[key] = img["file_key"]
            base.update(kind="image", image=key)
            labels.append("Image")
        elif it.kind == "text":
            text = _clean_text(it.text, 60)
            if not text:
                raise StampError("Stamp text can't be empty.")
            base.update(kind="text", text=text, color=_color(it.color, TEXT_COLORS["blue"]), border=bool(it.border))
            labels.append(f'Text "{text}"')
        elif it.kind == "date":
            fmt = it.date_format if it.date_format in stamp_pdf.DATE_FORMATS else settings["date_format"]
            text = stamp_pdf.format_date(now, fmt, bool(it.with_time))
            base.update(kind="text", text=text, color=_color(it.color, TEXT_COLORS["blue"]), border=False)
            labels.append(f"Date {text}")
        elif it.kind == "plain":
            text = _clean_text(it.text, 2000, multiline=True)
            if not text:
                continue                                   # an empty text box is simply dropped
            fs = float(it.fs or 0.014)
            if not 0.003 <= fs <= 0.2:
                raise StampError("Invalid text size.")
            base.update(kind="plain", text=text, fs=fs, font=it.font if it.font in stamp_pdf.FONTS else "helv",
                        bold=bool(it.bold), italic=bool(it.italic), color=_color(it.color, "#15141a"))
            labels.append("Text")
        elif it.kind == "shape":
            if it.shape not in stamp_pdf.SHAPES:
                raise StampError("Unknown shape.")
            sw = float(it.sw or 0.002)
            if not 0 < sw <= 0.05:
                raise StampError("Invalid line width.")
            base.update(kind="shape", shape=it.shape, stroke=_color(it.stroke, "#15141a"),
                        fill=_color(it.fill, None) if it.fill else None, sw=sw)
            labels.append({"whiteout": "Whiteout", "highlight": "Highlight", "check": "Checkmark",
                           "cross": "Cross", "dot": "Dot"}.get(it.shape, "Shape"))
        elif it.kind == "ink":
            pts = it.points or []
            if not 2 <= len(pts) <= 2000 or any(len(p) != 2 or not (-0.1 <= p[0] <= 1.1 and -0.1 <= p[1] <= 1.1)
                                                 for p in pts):
                raise StampError("Invalid drawing.")
            sw = float(it.sw or 0.002)
            if not 0 < sw <= 0.05:
                raise StampError("Invalid line width.")
            base.update(kind="ink", points=[[round(a, 5), round(b, 5)] for a, b in pts],
                        stroke=_color(it.stroke, "#15141a"), sw=sw)
            labels.append("Drawing")
        elif it.kind == "link":
            url = (it.url or "").strip()
            if not URL_RE.match(url):
                raise StampError("Links must start with https://, http:// or mailto:")
            for page in pages:
                links.append({"page": page, "x": it.x, "y": it.y, "w": it.w, "h": it.h, "url": url})
            labels.append("Link")
            continue
        elif it.kind == "signer":
            if not allow_signers:
                raise StampError("This document has boxes for other people to sign. "
                                 "Use “Send for signature” instead.")
            name = _clean_text(it.signer_name, 60)
            if not name:
                raise StampError("Give each signer a name.")
            if it.field not in SIGNER_FIELDS:
                raise StampError("Unknown signer field.")
            signers.append({"name": name, "contact": _clean_text(it.signer_contact, 120),
                            "field": it.field, "pages": pages, "geom": base})
            continue
        else:
            raise StampError("Unknown item type.")
        for page in pages:
            placements.append({**base, "page": page})
            if len(placements) > MAX_PLACEMENTS:
                raise StampError("Too many placements - reduce the page selection.")

    fields = {}
    if body.fields:
        try:
            known = {f["name"] for f in stamp_pdf.form_fields(
                stamp_pdf.open_pdf(stamp_files.get_storage().get(d["original_file_key"])))}
        except (StampError, stamp_files.StorageError):
            known = set()
        for name, value in list(body.fields.items())[:500]:
            if name in known:
                fields[name] = _clean_text(value, 2000, multiline=True)
    if not (placements or links or signers or any(v for v in fields.values())):
        raise StampError("Add at least one signature, stamp, text or other change before exporting.")
    return {"placements": placements, "image_keys": image_keys, "labels": labels, "links": links,
            "fields": fields, "signers": signers, "now": now}


def _load_images(image_keys: dict) -> dict:
    store = stamp_files.get_storage()
    try:
        return {k: store.get(v) for k, v in image_keys.items()}
    except stamp_files.StorageError:
        raise StampError("An image used on this document is missing. Re-add it and try again.", 500)


def _public_base(request: Request) -> str:
    base = os.environ.get("APP_URL", "").strip().rstrip("/")
    if base:
        return base
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return f"{proto}://{host}"


def _summary_labels(labels: list) -> list:
    return sorted(set(labels))


@router.post("/stamp/documents/{document_id}/preview-summary", dependencies=[Depends(same_origin)])
def preview_summary(document_id: str, body: Draft, request: Request):
    """What the confirmation screen shows - computed by the server with the
    same rules finalize uses, so the summary can't disagree with the result."""
    user = require_stamp(request)
    d = _get_doc(document_id, user, edit=True)
    if d["status"] not in ("DRAFT", "FAILED"):
        raise HTTPException(status_code=409, detail="This document has already been stamped")
    _not_out_for_signature(document_id)
    try:
        r = _resolve(body, d, user, allow_signers=True)
    except StampError as e:
        _fail(e)
    settings = stamp_store.get_settings()
    labels = r["labels"] + (["Form fields"] if any(r["fields"].values()) else [])
    signer_names = list(dict.fromkeys(s["name"] for s in r["signers"]))
    return {"document": d["original_filename"], "document_id": document_id,
            "pages": sorted({p["page"] for p in r["placements"]} | {s_p for s in r["signers"] for s_p in s["pages"]}),
            "page_count": d["page_count"], "stamps": _summary_labels(labels), "signed_by": user["username"],
            "signers": signer_names,
            "date": stamp_pdf.format_date(r["now"], settings["date_format"], True),
            "placements": len(r["placements"]), "company": settings["company_name"]}


def _produce(d: dict, plan: dict, images: dict, user: dict, base_url: str, *, appendix: bytes = None) -> dict:
    """Render -> hash -> store -> mark COMPLETED. The caller has already
    claimed the document (DRAFT/FAILED -> PROCESSING)."""
    settings = stamp_store.get_settings()
    store = stamp_files.get_storage()
    document_id = d["document_id"]
    original = store.get(d["original_file_key"])
    if stamp_pdf.sha256_hex(original) != d["original_sha256"]:
        raise StampError("The stored original no longer matches its recorded hash.", 500)
    footer = (f"Document ID: {document_id}  |  Registered by {settings['company_name']}"
              if settings.get("footer_enabled") else None)
    qr = stamp_pdf.qr_png(f"{base_url}/verify/{document_id}") if settings.get("qr_enabled") else None
    final = stamp_pdf.render(original, plan["placements"], images, document_id=document_id,
                             footer_text=footer, qr_png=qr,
                             qr_position=settings.get("qr_position") or "bottom-right",
                             company=settings["company_name"], appendix=appendix,
                             field_values=plan.get("fields") or {}, links=plan.get("links") or [])
    stamp_pdf.open_pdf(final)                 # the result must itself be a readable PDF
    final_hash = stamp_pdf.sha256_hex(final)  # hashed LAST - nothing touches the bytes after this
    final_key = store.put(final, "pdf")
    summary = {"stamps": _summary_labels(plan["labels"]), "placements": len(plan["placements"]),
               "pages": sorted({p["page"] for p in plan["placements"]}),
               "qr": bool(qr), "footer": bool(footer), "stamped_at_local": plan.get("stamped_at_local", "")}
    if plan.get("signers"):
        summary["signers"] = plan["signers"]
    stamp_store.complete_document(document_id, final_file_key=final_key, final_sha256=final_hash,
                                  final_size=len(final), placements=plan["placements"],
                                  summary=summary, user=user)
    return {"final_sha256": final_hash, "summary": summary}


@router.post("/stamp/documents/{document_id}/finalize", dependencies=[Depends(same_origin)])
def finalize(document_id: str, body: Draft, request: Request):
    user = require_stamp(request)
    d = _get_doc(document_id, user, edit=True)
    if d["status"] in ("COMPLETED", "VOID", "PROCESSING"):
        raise HTTPException(status_code=409, detail="This document has already been stamped. "
                                                    "Upload it again to create a new stamped copy.")
    _not_out_for_signature(document_id)
    try:
        r = _resolve(body, d, user)
        images = _load_images(r["image_keys"])
    except StampError as e:
        _fail(e)
    settings = stamp_store.get_settings()
    labels = r["labels"] + (["Form fields"] if any(r["fields"].values()) else [])
    plan = {"placements": r["placements"], "labels": labels, "links": r["links"], "fields": r["fields"],
            "stamped_at_local": stamp_pdf.format_date(r["now"], settings["date_format"], True)}
    if not stamp_store.claim_for_processing(document_id):
        raise HTTPException(status_code=409, detail="This document is already being processed")
    try:
        out = _produce(d, plan, images, user, _public_base(request))
    except StampError as e:
        stamp_store.mark_failed(document_id)
        _audit(request, "DOCUMENT_STAMP_FAILED", user, document_id, reason=e.message)
        _fail(e)
    except Exception as exc:
        stamp_store.mark_failed(document_id)
        print(f"stamp finalize failed for {document_id}: {exc!r}")
        _audit(request, "DOCUMENT_STAMP_FAILED", user, document_id, reason="internal error")
        raise HTTPException(status_code=500, detail="Document generation failed. Nothing was changed - please try again.")
    _audit(request, "DOCUMENT_STAMPED", user, document_id, final_sha256=out["final_sha256"],
           original_sha256=d["original_sha256"], placements=len(r["placements"]), stamps=out["summary"]["stamps"])
    return _doc_view(stamp_store.get_document(document_id), user)


@router.get("/stamp/documents/{document_id}/download")
def download(document_id: str, request: Request):
    user = auth.require_auth(request)
    d = _get_doc(document_id, user)
    if d["status"] not in ("COMPLETED", "VOID") or not d["final_file_key"]:
        raise HTTPException(status_code=409, detail="This document has not been stamped yet")
    try:
        data = stamp_files.get_storage().get(d["final_file_key"])
    except stamp_files.StorageError:
        raise HTTPException(status_code=404, detail="File not available")
    _audit(request, "DOCUMENT_DOWNLOADED", user, document_id)
    return Response(content=data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{document_id}_Stamped.pdf"',
        "Cache-Control": "private, no-store"})


class VoidBody(BaseModel):
    reason: str


@router.post("/stamp/documents/{document_id}/void", dependencies=[Depends(same_origin)])
def void_document(document_id: str, body: VoidBody, request: Request):
    user = require_stamp_admin(request)
    _get_doc(document_id, user)
    reason = (body.reason or "").strip()[:300]
    if len(reason) < 3:
        raise HTTPException(status_code=422, detail="Give a short reason for voiding this document")
    if not stamp_store.void_document(document_id, user, reason):
        raise HTTPException(status_code=409, detail="Only a completed document can be voided")
    _audit(request, "DOCUMENT_VOIDED", user, document_id, reason=reason)
    return _doc_view(stamp_store.get_document(document_id), user)


@router.get("/stamp/documents/{document_id}/audit")
def document_audit(document_id: str, request: Request):
    user = auth.require_auth(request)
    d = _get_doc(document_id, user)
    events = stamp_store.list_audit(document_id=d["document_id"], limit=300)
    if not _is_admin(user):           # only directors see IP addresses / user agents
        for e in events:
            e.pop("ip_address", None); e.pop("user_agent", None)
    return events


# --- stamps ----------------------------------------------------------------

@router.get("/stamp/stamps")
def list_stamps(request: Request):
    user = auth.require_auth(request)
    if _is_admin(user):
        return stamp_store.list_stamps(include_inactive=True)
    if not auth.can(user["role"], "stamp"):
        return []
    return _usable_stamps(user)


@router.get("/stamp/stamps/{stamp_id}/image")
def stamp_image(stamp_id: int, request: Request):
    user = require_stamp(request)
    row = stamp_store.get_stamp_row(stamp_id)
    if not row or not row["file_key"]:
        raise HTTPException(status_code=404, detail="Stamp not found")
    if not _is_admin(user) and (not row["active"] or user["role"] not in (row["allowed_roles"] or "").split(",")):
        raise HTTPException(status_code=403, detail="You do not have permission to use this stamp")
    try:
        data = stamp_files.get_storage().get(row["file_key"])
    except stamp_files.StorageError:
        raise HTTPException(status_code=404, detail="Stamp image missing")
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "private, no-store"})


def _roles(value: str) -> str:
    roles = [r for r in (value or "").split(",") if r in ("director", "admin")]
    if "director" not in roles:
        roles.insert(0, "director")
    return ",".join(dict.fromkeys(roles))


def _name(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    if not value or len(value) > 40:
        raise HTTPException(status_code=422, detail="Stamp name must be 1-40 characters")
    return value


@router.post("/stamp/stamps", dependencies=[Depends(same_origin)])
async def create_stamp(request: Request, name: str, category: str = "custom", kind: str = "image",
                       text: str = "", color: str = "blue", roles: str = "director,admin"):
    user = require_stamp_admin(request)
    name = _name(name)
    category = category if category in CATEGORIES else "custom"
    if kind == "text":
        text = re.sub(r"\s+", " ", text).strip()
        if not text or len(text) > 40:
            raise HTTPException(status_code=422, detail="Stamp text must be 1-40 characters")
        try:
            text.encode("latin-1")
        except UnicodeEncodeError:
            raise HTTPException(status_code=422, detail="Stamp text can only use standard Latin characters")
        sid = stamp_store.create_stamp(name=name, category=category, kind="text", text=text,
                                       color=TEXT_COLORS.get(color, TEXT_COLORS["blue"]),
                                       allowed_roles=_roles(roles), created_by=user["id"])
    else:
        png = _png(await _body(request, MAX_IMAGE_BYTES))
        key = stamp_files.get_storage().put(png, "png")
        sid = stamp_store.create_stamp(name=name, category=category, kind="image", file_key=key,
                                       mime_type="image/png", allowed_roles=_roles(roles),
                                       created_by=user["id"])
    _audit(request, "STAMP_CREATED", user, None, stamp_id=sid, name=name, kind=kind)
    return next(s for s in stamp_store.list_stamps(True) if s["id"] == sid)


class StampPatch(BaseModel):
    name: str | None = None
    category: str | None = None
    roles: str | None = None
    active: bool | None = None


@router.put("/stamp/stamps/{stamp_id}", dependencies=[Depends(same_origin)])
def update_stamp(stamp_id: int, body: StampPatch, request: Request):
    user = require_stamp_admin(request)
    row = stamp_store.get_stamp_row(stamp_id)
    if not row:
        raise HTTPException(status_code=404, detail="Stamp not found")
    fields = {}
    if body.name is not None:
        fields["name"] = _name(body.name)
    if body.category is not None and body.category in CATEGORIES:
        fields["category"] = body.category
    if body.roles is not None:
        fields["allowed_roles"] = _roles(body.roles)
    if body.active is not None:
        fields["active"] = body.active
    stamp_store.update_stamp(stamp_id, fields)
    disabled = body.active is False and row["active"]
    _audit(request, "STAMP_DISABLED" if disabled else "STAMP_UPDATED", user, None,
           stamp_id=stamp_id, name=fields.get("name", row["name"]), changed=sorted(fields))
    return next(s for s in stamp_store.list_stamps(True) if s["id"] == stamp_id)


@router.post("/stamp/stamps/{stamp_id}/image", dependencies=[Depends(same_origin)])
async def replace_stamp_image(stamp_id: int, request: Request):
    """Replace the image (e.g. the official chop). The old file stays in
    storage - documents already stamped are separate files and never change."""
    user = require_stamp_admin(request)
    row = stamp_store.get_stamp_row(stamp_id)
    if not row or row["kind"] != "image":
        raise HTTPException(status_code=404, detail="Stamp not found")
    key = stamp_files.get_storage().put(_png(await _body(request, MAX_IMAGE_BYTES)), "png")
    stamp_store.update_stamp(stamp_id, {"file_key": key, "mime_type": "image/png"})
    _audit(request, "STAMP_UPDATED", user, None, stamp_id=stamp_id, name=row["name"], changed=["image"])
    return next(s for s in stamp_store.list_stamps(True) if s["id"] == stamp_id)


# --- signatures & initials (strictly the caller's own) ------------------------

def _trim_png(png: bytes) -> bytes:
    img = Image.open(io.BytesIO(png))
    box = img.getbbox()                       # trim the empty margin so it sizes sensibly
    if not box:
        raise HTTPException(status_code=400, detail="The signature is empty - draw or upload it again.")
    out = io.BytesIO()
    img.crop(box).save(out, "PNG", optimize=True)
    return out.getvalue()


@router.get("/stamp/signatures")
def my_signatures(request: Request):
    user = require_stamp(request)
    return stamp_store.list_signatures(user["id"])


@router.get("/stamp/signatures/{sig_id}/image")
def my_signature_image(sig_id: int, request: Request):
    user = require_stamp(request)
    sig = stamp_store.get_own_signature(user["id"], sig_id)
    if not sig:
        raise HTTPException(status_code=404, detail="Signature not found")
    try:
        data = stamp_files.get_storage().get(sig["file_key"])
    except stamp_files.StorageError:
        raise HTTPException(status_code=404, detail="Signature not found")
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.post("/stamp/signatures", dependencies=[Depends(same_origin)])
async def add_signature(request: Request, kind: str = "signature", saved: bool = True):
    user = require_stamp(request)
    kind = "initials" if kind == "initials" else "signature"
    png = _trim_png(_png(await _body(request, MAX_IMAGE_BYTES)))
    sid = stamp_store.add_signature(user["id"], stamp_files.get_storage().put(png, "png"), kind, saved)
    _audit(request, "SIGNATURE_UPDATED", user, None, signature_id=sid, kind=kind, saved=saved)
    return {"id": sid, "kind": kind}


@router.delete("/stamp/signatures/{sig_id}", dependencies=[Depends(same_origin)])
def delete_signature(sig_id: int, request: Request):
    user = require_stamp(request)
    if not stamp_store.remove_signature(user["id"], sig_id):
        raise HTTPException(status_code=404, detail="Signature not found")
    _audit(request, "SIGNATURE_REMOVED", user, None, signature_id=sig_id)
    return {"ok": True}


# --- images placed on one document ---------------------------------------------

@router.post("/stamp/documents/{document_id}/images", dependencies=[Depends(same_origin)])
async def add_doc_image(document_id: str, request: Request):
    user = require_stamp(request)
    d = _get_doc(document_id, user, edit=True)
    png = _png(await _body(request, MAX_IMAGE_BYTES))
    iid = stamp_store.add_doc_image(d["document_id"], stamp_files.get_storage().put(png, "png"), user["id"])
    return {"id": iid}


@router.get("/stamp/documents/{document_id}/images/{image_id}")
def doc_image(document_id: str, image_id: int, request: Request):
    user = require_stamp(request)
    d = _get_doc(document_id, user)
    img = stamp_store.get_doc_image(d["document_id"], image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    try:
        data = stamp_files.get_storage().get(img["file_key"])
    except stamp_files.StorageError:
        raise HTTPException(status_code=404, detail="Image not found")
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "private, no-store"})


# --- sending a document for other people to sign ---------------------------------
# The sender places boxes for each signer, then gets one private link per
# signer to pass on (WhatsApp, email...). Signers need no account. When the
# last one signs, the stamped copy is produced automatically with a signature
# certificate page, hashed and registered like any other document.

def _sign_url(base: str, token: str) -> str:
    return f"{base}/sign/{token}"


def _signing_view(document_id: str) -> dict:
    sg = stamp_store.get_signing(document_id)
    if not sg:
        return None
    reqs = [r for r in stamp_store.list_sign_requests(document_id) if r["status"] != "CANCELLED"
            or sg["status"] == "CANCELLED"]
    return {"status": sg["status"], "created_at": sg["created_at"], "created_by_name": sg["created_by_name"],
            "requests": [{"id": r["id"], "name": r["signer_name"], "contact": r["signer_contact"],
                          "status": r["status"], "signed_at": r["signed_at"],
                          "decline_reason": r["decline_reason"]} for r in reqs]}


@router.post("/stamp/documents/{document_id}/send-for-signature", dependencies=[Depends(same_origin)])
def send_for_signature(document_id: str, body: Draft, request: Request):
    user = require_stamp(request)
    d = _get_doc(document_id, user, edit=True)
    if d["status"] not in ("DRAFT", "FAILED"):
        raise HTTPException(status_code=409, detail="This document has already been stamped")
    _not_out_for_signature(document_id)
    try:
        r = _resolve(body, d, user, allow_signers=True)
        _load_images(r["image_keys"])                     # fail now, not when the last person signs
    except StampError as e:
        _fail(e)
    if not r["signers"]:
        raise HTTPException(status_code=422, detail="Add at least one box for someone else to sign.")
    people = {}
    for s in r["signers"]:
        people.setdefault(s["name"].lower(), {"name": s["name"], "contact": s["contact"]})
        if s["contact"] and not people[s["name"].lower()]["contact"]:
            people[s["name"].lower()]["contact"] = s["contact"]
    if len(people) > MAX_SIGNERS:
        raise HTTPException(status_code=422, detail=f"Up to {MAX_SIGNERS} people can sign one document.")
    settings = stamp_store.get_settings()
    plan = {"placements": r["placements"], "image_keys": r["image_keys"], "links": r["links"],
            "fields": r["fields"],
            "labels": r["labels"] + (["Form fields"] if any(r["fields"].values()) else []),
            "signer_items": [{"idx": i, "name": s["name"], "field": s["field"], "pages": s["pages"],
                              "geom": s["geom"]} for i, s in enumerate(r["signers"])],
            "stamped_at_local": stamp_pdf.format_date(r["now"], settings["date_format"], True),
            "sent_at": stamp_pdf.format_date(r["now"], settings["date_format"], True)}
    stamp_store.save_draft(document_id, {"items": [i.model_dump(exclude_none=True) for i in body.items],
                                         "fields": body.fields})
    links = stamp_store.open_signing(document_id, plan, list(people.values()), user)
    base = _public_base(request)
    _audit(request, "SIGNATURE_REQUESTED", user, document_id, signers=[p["name"] for p in people.values()])
    return {"links": [{"name": people[k]["name"], "request_id": rid, "url": _sign_url(base, tok)}
                      for k, (rid, tok) in links.items()],
            "document": _doc_view(stamp_store.get_document(document_id), user)}


def _owner_signing(document_id: str, request: Request):
    user = require_stamp(request)
    d = _get_doc(document_id, user, edit=False)
    if not (_is_admin(user) or d["created_by"] == user["id"]):
        raise HTTPException(status_code=403, detail="You do not have permission to manage this document")
    return user, d


@router.get("/stamp/documents/{document_id}/signing")
def signing_status(document_id: str, request: Request):
    _owner_signing(document_id, request)
    return _signing_view(document_id) or {"status": None, "requests": []}


@router.post("/stamp/documents/{document_id}/signing/{request_id}/link", dependencies=[Depends(same_origin)])
def renew_link(document_id: str, request_id: int, request: Request):
    """Links are shown once; this issues a fresh one and the old one stops working."""
    user, d = _owner_signing(document_id, request)
    sg = stamp_store.get_signing(document_id)
    req = next((r for r in stamp_store.list_sign_requests(document_id) if r["id"] == request_id), None)
    if not sg or sg["status"] != "OPEN" or not req or req["status"] != "PENDING":
        raise HTTPException(status_code=409, detail="This person has already responded")
    token = stamp_store.renew_sign_token(request_id)
    _audit(request, "SIGNATURE_LINK_RENEWED", user, document_id, signer=req["signer_name"])
    return {"url": _sign_url(_public_base(request), token)}


@router.post("/stamp/documents/{document_id}/signing/cancel", dependencies=[Depends(same_origin)])
def cancel_signing(document_id: str, request: Request):
    user, d = _owner_signing(document_id, request)
    if not stamp_store.cancel_signing(document_id):
        raise HTTPException(status_code=409, detail="There is no open signature request")
    _audit(request, "SIGNATURE_REQUEST_CANCELLED", user, document_id)
    return _doc_view(stamp_store.get_document(document_id), user)


@router.post("/stamp/documents/{document_id}/signing/complete", dependencies=[Depends(same_origin)])
def retry_signing(document_id: str, request: Request):
    user, d = _owner_signing(document_id, request)
    msg = _try_complete(document_id, _public_base(request), request)
    if msg:
        raise HTTPException(status_code=409, detail=msg)
    return _doc_view(stamp_store.get_document(document_id), user)


def _local_time(iso: str, settings: dict) -> str:
    if not iso:
        return ""
    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=stamp_store.timezone.utc)
    return stamp_pdf.format_date(dt.astimezone(stamp_store.get_tz(settings.get("timezone"))),
                                 settings["date_format"], True)


def _try_complete(document_id: str, base_url: str, request: Request):
    """Produce the final file once every signer has signed. Returns None on
    success (or when there is nothing to do yet) and a message otherwise."""
    sg = stamp_store.get_signing(document_id)
    if not sg or sg["status"] != "OPEN":
        return "There is no open signature request"
    reqs = [r for r in stamp_store.list_sign_requests(document_id) if r["status"] != "CANCELLED"]
    if not reqs or any(r["status"] != "SIGNED" for r in reqs):
        return "Not everyone has signed yet"
    d = stamp_store.get_document(document_id)
    owner_row = storage.get_user_by_id(sg["created_by"]) or {}
    owner = {"id": sg["created_by"], "username": owner_row.get("username") or sg["created_by_name"]}
    settings = stamp_store.get_settings()
    plan = dict(sg["plan"])
    store = stamp_files.get_storage()
    try:
        images = _load_images(plan.get("image_keys") or {})
        placements = list(plan["placements"])
        by_id = {r["id"]: r for r in reqs}
        for si in plan.get("signer_items", []):
            r = by_id.get(plan["request_ids"].get(si["name"].lower()))
            if not r:
                continue
            g = dict(si["geom"])
            values = json.loads(r.get("values_json") or "{}")
            if si["field"] in ("signature", "initials"):
                fk = r["signature_file_key"] if si["field"] == "signature" else r["initials_file_key"]
                key = f"e{si['field']}{r['id']}"
                images[key] = store.get(fk)
                piece = {**g, "kind": "image", "image": key}
            else:
                text = (values.get(str(si["idx"])) if si["field"] == "text"
                        else _local_time(r["signed_at"], settings).rsplit(" ", 2)[0])
                if not text:
                    continue
                fs = min(g["h"] * 0.62, 0.025)
                piece = {**g, "kind": "plain", "text": text, "font": "helv", "fs": fs, "color": "#15141a",
                         "y": g["y"] + max(0.0, (g["h"] - fs * stamp_pdf.LINE_HEIGHT) / 2)}
            for page in si["pages"]:
                placements.append({**piece, "page": page})
        plan["placements"] = placements
        plan["labels"] = list(plan.get("labels", [])) + [f"E-signature: {r['signer_name']}" for r in reqs]
        plan["signers"] = [{"name": r["signer_name"], "signed_at": _local_time(r["signed_at"], settings)}
                           for r in reqs]
        cert = stamp_pdf.certificate_pdf({
            "document_id": document_id, "filename": d["original_filename"],
            "original_sha256": d["original_sha256"], "company": settings["company_name"],
            "registration": settings["registration_number"], "sent_by": owner["username"],
            "sent_at": _local_time(sg["created_at"], settings),
            "completed_at": stamp_pdf.format_date(datetime.now(stamp_store.get_tz(settings.get("timezone"))),
                                                  settings["date_format"], True),
            "signers": [{"name": r["signer_name"], "contact": r["signer_contact"],
                         "signed_at": _local_time(r["signed_at"], settings), "ip": r["signer_ip"],
                         "user_agent": r["signer_user_agent"]} for r in reqs]})
    except (StampError, stamp_files.StorageError, KeyError, ValueError) as exc:
        print(f"e-sign completion failed for {document_id}: {exc!r}")
        return "A signature file is missing. Cancel and send the document again."
    if not stamp_store.claim_for_processing(document_id):
        return None                                   # someone else is finishing it right now
    try:
        out = _produce(d, plan, images, owner, base_url, appendix=cert)
    except Exception as exc:
        stamp_store.mark_failed(document_id)
        print(f"e-sign finalize failed for {document_id}: {exc!r}")
        _audit(request, "DOCUMENT_STAMP_FAILED", owner, document_id, reason="e-sign completion failed")
        return "Document generation failed. Try “Finish now” again from Documents."
    stamp_store.close_signing(document_id)
    _audit(request, "DOCUMENT_STAMPED", owner, document_id, final_sha256=out["final_sha256"],
           original_sha256=d["original_sha256"], esign=True, signers=[r["signer_name"] for r in reqs])
    return None


# --- the signer's side (public, link-only) ----------------------------------------

def _signer_request(token: str, request: Request) -> tuple:
    _rate_limit(_ip(request))
    r = stamp_store.get_sign_request_by_token(token)
    if not r:
        raise HTTPException(status_code=404, detail="This signing link is not valid. Ask the sender for a new link.")
    sg = stamp_store.get_signing(r["document_id"])
    d = stamp_store.get_document(r["document_id"])
    if not sg or not d:
        raise HTTPException(status_code=404, detail="This signing link is not valid. Ask the sender for a new link.")
    return r, sg, d


def _my_fields(r: dict, sg: dict) -> list:
    out = []
    for si in sg["plan"].get("signer_items", []):
        if si["name"].lower() != r["signer_name"].lower():
            continue
        g = si["geom"]
        for page in si["pages"]:
            out.append({"idx": si["idx"], "field": si["field"], "page": page, "x": g["x"], "y": g["y"],
                        "w": g["w"], "h": g["h"], "rotation": g.get("rotation", 0)})
    return out


@router.get("/sign/{token}")
def signer_info(token: str, request: Request):
    r, sg, d = _signer_request(token, request)
    settings = stamp_store.get_settings()
    others = [x for x in stamp_store.list_sign_requests(d["document_id"]) if x["status"] != "CANCELLED"]
    return {"status": r["status"] if sg["status"] != "CANCELLED" else "CANCELLED",
            "signer_name": r["signer_name"], "document_id": d["document_id"],
            "filename": d["original_filename"], "page_count": d["page_count"],
            "sender": sg["created_by_name"], "company": settings["company_name"],
            "completed": d["status"] == "COMPLETED", "void": d["status"] == "VOID",
            "signed_count": sum(1 for x in others if x["status"] == "SIGNED"), "total": len(others),
            "date_preview": stamp_pdf.format_date(datetime.now(stamp_store.get_tz(settings.get("timezone"))),
                                                  settings["date_format"]),
            "fields": _my_fields(r, sg) if r["status"] == "PENDING" and sg["status"] == "OPEN" else []}


@router.get("/sign/{token}/file")
def signer_file(token: str, request: Request):
    r, sg, d = _signer_request(token, request)
    if sg["status"] == "CANCELLED" or r["status"] in ("CANCELLED", "DECLINED"):
        raise HTTPException(status_code=410, detail="This signature request is no longer active.")
    key = d["final_file_key"] if d["status"] in ("COMPLETED", "VOID") else d["original_file_key"]
    data = stamp_files.get_storage().get(key)
    headers = {"Cache-Control": "private, no-store", "Content-Disposition": "inline"}
    if d["status"] in ("COMPLETED", "VOID") and request.query_params.get("download"):
        headers["Content-Disposition"] = f'attachment; filename="{d["document_id"]}_Signed.pdf"'
    return Response(content=data, media_type="application/pdf", headers=headers)


def _data_url_png(value: str) -> bytes:
    import base64
    m = re.match(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$", value or "")
    if not m:
        raise HTTPException(status_code=400, detail="The signature could not be read. Please sign again.")
    return _trim_png(_png(base64.b64decode(m.group(2))))


@router.post("/sign/{token}")
async def signer_submit(token: str, request: Request):
    r, sg, d = _signer_request(token, request)
    if sg["status"] != "OPEN" or r["status"] != "PENDING":
        raise HTTPException(status_code=409, detail="This request has already been answered or withdrawn.")
    try:
        body = json.loads(await _body(request, 8 * 1024 * 1024))
    except ValueError:
        raise HTTPException(status_code=400, detail="Something went wrong. Please try again.")
    if body.get("consent") is not True:
        raise HTTPException(status_code=422, detail="Tick the box to agree to sign electronically.")
    fields = _my_fields(r, sg)
    need = {f["field"] for f in fields}
    store = stamp_files.get_storage()
    sig_key = ini_key = None
    if "signature" in need:
        sig_key = store.put(_data_url_png(body.get("signature")), "png")
    if "initials" in need:
        ini_key = store.put(_data_url_png(body.get("initials")), "png")
    texts = body.get("texts") or {}
    values = {}
    for f in fields:
        if f["field"] == "text":
            try:
                v = _clean_text(str(texts.get(str(f["idx"]), "")), 200)
            except StampError as e:
                raise HTTPException(status_code=422, detail=e.message)
            if not v:
                raise HTTPException(status_code=422, detail="Fill in every text box before finishing.")
            values[str(f["idx"])] = v
    if not stamp_store.record_signature(r["id"], sig_key, ini_key, values, _ip(request), _ua(request)):
        raise HTTPException(status_code=409, detail="This request has already been answered.")
    _audit(request, "DOCUMENT_SIGNED", None, d["document_id"], signer=r["signer_name"])
    _try_complete(d["document_id"], _public_base(request), request)
    return signer_info(token, request)


class Decline(BaseModel):
    reason: str = ""


@router.post("/sign/{token}/decline")
def signer_decline(token: str, body: Decline, request: Request):
    r, sg, d = _signer_request(token, request)
    if sg["status"] != "OPEN" or r["status"] != "PENDING":
        raise HTTPException(status_code=409, detail="This request has already been answered or withdrawn.")
    reason = re.sub(r"\s+", " ", body.reason or "").strip()[:300]
    stamp_store.decline_request(r["id"], reason, _ip(request), _ua(request))
    _audit(request, "SIGNATURE_DECLINED", None, d["document_id"], signer=r["signer_name"], reason=reason)
    return signer_info(token, request)


# --- audit + settings (director) ---------------------------------------------

@router.get("/stamp/audit")
def audit_trail(request: Request, event_type: str = None, document_id: str = None, limit: int = 300):
    require_stamp_admin(request)
    return stamp_store.list_audit(document_id=document_id or None, event_type=event_type or None, limit=limit)


@router.get("/stamp/settings")
def get_settings(request: Request):
    require_stamp_admin(request)
    return stamp_store.get_settings()


class SettingsBody(BaseModel):
    company_name: str | None = None
    registration_number: str | None = None
    location: str | None = None
    date_format: str | None = None
    default_stamp_size: float | None = None
    qr_enabled: bool | None = None
    qr_position: str | None = None
    footer_enabled: bool | None = None
    max_upload_mb: int | None = None
    public_show_filename: bool | None = None


@router.put("/stamp/settings", dependencies=[Depends(same_origin)])
def put_settings(body: SettingsBody, request: Request):
    user = require_stamp_admin(request)
    v = {k: val for k, val in body.model_dump().items() if val is not None}
    for k in ("company_name", "registration_number", "location"):
        if k in v:
            v[k] = re.sub(r"\s+", " ", v[k]).strip()[:80]
            if not v[k]:
                raise HTTPException(status_code=422, detail="Company details can't be blank")
    if "date_format" in v and v["date_format"] not in stamp_pdf.DATE_FORMATS:
        raise HTTPException(status_code=422, detail="Unknown date format")
    if "qr_position" in v and v["qr_position"] not in ("bottom-right", "bottom-left", "top-right", "top-left"):
        raise HTTPException(status_code=422, detail="Unknown QR position")
    if "default_stamp_size" in v:
        v["default_stamp_size"] = max(0.08, min(0.6, v["default_stamp_size"]))
    if "max_upload_mb" in v:
        v["max_upload_mb"] = max(1, min(50, v["max_upload_mb"]))
    stamp_store.save_settings(v, user["id"])
    _audit(request, "SETTINGS_UPDATED", user, None, changed=sorted(v))
    return stamp_store.get_settings()


# --- verification (public) ---------------------------------------------------

_VERIFY_HITS: dict = {}
_VERIFY_WINDOW, _VERIFY_MAX = 300, 40


def _rate_limit(ip: str):
    now = time.time()
    hits = [t for t in _VERIFY_HITS.get(ip, []) if now - t < _VERIFY_WINDOW]
    hits.append(now)
    _VERIFY_HITS[ip] = hits
    if len(_VERIFY_HITS) > 5000:
        for k in [k for k, v in list(_VERIFY_HITS.items()) if not v or now - v[-1] > _VERIFY_WINDOW]:
            _VERIFY_HITS.pop(k, None)
    if len(hits) > _VERIFY_MAX:
        raise HTTPException(status_code=429, detail="Too many verification attempts. Wait a few minutes.")


def _public(d: dict, status: str, message: str) -> dict:
    """Only what is safe for anyone holding the document to see. No user
    names, filenames (unless enabled), storage paths, IPs or audit data."""
    s = stamp_store.get_settings()
    out = {"status": status, "message": message, "company": s["company_name"],
           "registration_number": s["registration_number"]}
    if d:
        tz = stamp_store.get_tz(s.get("timezone"))
        issued = d.get("completed_at")
        if issued:
            dt = datetime.strptime(issued, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=stamp_store.timezone.utc)
            out["issued"] = stamp_pdf.format_date(dt.astimezone(tz), "DD MMM YYYY").title()
        out["document_id"] = d["document_id"]
        if s.get("public_show_filename"):
            out["filename"] = d["original_filename"]
    return out


def _result(d: dict, matched: bool, by_file: bool) -> dict:
    company = stamp_store.get_settings()["company_name"]
    if not d or d["status"] not in ("COMPLETED", "VOID"):
        return _public(None, "NOT_FOUND",
                       "No matching document was found in the Code N Code document registry.")
    if d["status"] == "VOID":
        return _public(d, "VOID", f"This document was previously registered by {company} "
                                  "but has subsequently been marked void.")
    if by_file and matched:
        return _public(d, "VERIFIED", "Document matches the registered stamped file.")
    if by_file:
        return _public(d, "MISMATCH", f"The uploaded file does not match the version registered by {company}.")
    return _public(d, "REGISTERED", f"This Document ID is registered by {company}. "
                                    "Upload the PDF to confirm the file itself matches.")


@router.get("/verify/{document_id}")
def verify_by_id(document_id: str, request: Request):
    ip = _ip(request)
    _rate_limit(ip)
    document_id = (document_id or "").strip().upper()
    d = stamp_store.get_document(document_id) if DOC_ID_RE.match(document_id) else None
    res = _result(d, False, False)
    stamp_store.log_verification(document_id[:40], "id", res["status"], ip)
    ok = res["status"] == "REGISTERED"
    _audit(request, "DOCUMENT_VERIFIED" if ok else "DOCUMENT_VERIFICATION_FAILED",
           auth.current_user(request), d["document_id"] if d else None, method="id", result=res["status"])
    return res


@router.post("/verify")
async def verify_by_file(request: Request, document_id: str = None):
    """Hash the uploaded bytes and look that hash up. The file is never
    stored. If it isn't an exact match but carries one of our Document IDs
    (typed in, or embedded when we stamped it), report a mismatch."""
    ip = _ip(request)
    _rate_limit(ip)
    data = await _body(request, _max_upload_bytes())
    if len(data) < 100 or b"%PDF-" not in data[:1024]:
        raise HTTPException(status_code=400, detail="Only PDF files can be verified.")
    digest = stamp_pdf.sha256_hex(data)
    d = stamp_store.find_by_final_hash(digest)
    matched = d is not None
    if not d:
        claimed = (document_id or "").strip().upper()
        if not DOC_ID_RE.match(claimed):
            claimed = stamp_pdf.embedded_document_id(data) or ""
        d = stamp_store.get_document(claimed) if claimed else None
    res = _result(d, matched, True)
    res["sha256"] = digest
    stamp_store.log_verification(d["document_id"] if d else None, "file", res["status"], ip)
    _audit(request, "DOCUMENT_VERIFIED" if res["status"] == "VERIFIED" else "DOCUMENT_VERIFICATION_FAILED",
           auth.current_user(request), d["document_id"] if d else None, method="file",
           result=res["status"], sha256=digest)
    return res
