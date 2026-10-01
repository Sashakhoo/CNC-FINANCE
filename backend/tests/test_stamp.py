"""Document Centre tests: permissions, upload validation, page ranges,
coordinate conversion, generation, hashes, IDs, verification, voiding."""
import io
import re
import secrets

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

import auth
import storage
import stamp_pdf
import stamp_store
import main

ORIGIN = {"Origin": "http://testserver"}
PW = secrets.token_urlsafe(12)          # generated per run - no real credentials in source


def make_pdf(pages=3, rotate=0, text="Agreement"):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842), pageCompression=0)
    for i in range(pages):
        c.drawString(72, 770, f"{text} - page {i + 1}")
        c.showPage()
    c.save()
    if not rotate:
        return buf.getvalue()
    w = PdfWriter()
    for p in PdfReader(io.BytesIO(buf.getvalue())).pages:
        p.rotate(rotate)
        w.add_page(p)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


@pytest.fixture(scope="session")
def app_client():
    with TestClient(main.app) as c:      # runs startup: tables + default stamps
        for name, role in (("boss", "director"), ("staff", "admin"), ("staff2", "admin"), ("reader", "viewer")):
            if not storage.get_user(name):
                salt, h = auth.hash_new(PW)
                storage.create_user(name, salt, h, role)
        yield c


def login(name):
    c = TestClient(main.app)
    r = c.post("/api/login", json={"username": name, "password": PW})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture(scope="session")
def boss(app_client):
    return login("boss")


@pytest.fixture(scope="session")
def staff(app_client):
    return login("staff")


@pytest.fixture(scope="session")
def staff2(app_client):
    return login("staff2")


@pytest.fixture(scope="session")
def reader(app_client):
    return login("reader")


def upload(c, data=None, name="Agreement.pdf"):
    return c.post("/api/stamp/documents", params={"filename": name},
                  content=make_pdf() if data is None else data,
                  headers={**ORIGIN, "Content-Type": "application/pdf"})


def chop_id(c):
    return next(s["id"] for s in c.get("/api/stamp/config").json()["stamps"] if s["kind"] == "image")


def item(stamp_id, **kw):
    return {"kind": "stamp", "stamp_id": stamp_id, "page": 1, "pages": "current",
            "x": 0.6, "y": 0.7, "w": 0.25, "h": 0.18, "rotation": 0, "opacity": 1, **kw}


def stamp(c, **kw):
    doc = upload(c).json()
    r = c.post(f"/api/stamp/documents/{doc['document_id']}/finalize",
               json={"items": [item(chop_id(c), **kw)]}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


# --- pure functions ---------------------------------------------------------

def test_page_ranges():
    assert stamp_pdf.parse_pages("current", 10, 4) == [4]
    assert stamp_pdf.parse_pages("all", 3) == [1, 2, 3]
    assert stamp_pdf.parse_pages("first", 9) == [1]
    assert stamp_pdf.parse_pages("last", 9) == [9]
    assert stamp_pdf.parse_pages("1,3,5-8", 10) == [1, 3, 5, 6, 7, 8]
    for bad in ("0", "11", "5-2", "a,b", "1;2", ",", "3-"):
        with pytest.raises(stamp_pdf.StampError):
            stamp_pdf.parse_pages(bad, 10)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("crop", [(0, 0, 595, 842), (20, 30, 500, 700)])
def test_coordinate_conversion(rotation, crop):
    """A box given as fractions of the DISPLAYED page must land on the same
    spot whatever the page's /Rotate and CropBox origin are."""
    x0, y0, x1, y1 = crop
    cw, ch = x1 - x0, y1 - y0
    dw, dh = (ch, cw) if rotation in (90, 270) else (cw, ch)
    fx, fy, fw, fh = 0.10, 0.20, 0.30, 0.15
    left, bottom, right, top = stamp_pdf.placement_rect(crop, rotation, fx, fy, fw, fh)["bbox"]
    got = (left, right, bottom, top)
    # Expected rectangle in unrotated PDF user space, derived independently.
    L, T, W, H = fx * dw, fy * dh, fw * dw, fh * dh        # display units, top-left origin
    if rotation == 0:
        exp = (x0 + L, x0 + L + W, y1 - T - H, y1 - T)
    elif rotation == 90:
        exp = (x0 + T, x0 + T + H, y0 + L, y0 + L + W)
    elif rotation == 180:
        exp = (x1 - L - W, x1 - L, y0 + T, y0 + T + H)
    else:
        exp = (x1 - T - H, x1 - T, y1 - L - W, y1 - L)
    assert got == pytest.approx(exp, abs=1e-6)


def test_date_format_and_id_shape():
    from datetime import datetime
    d = datetime(2026, 7, 9, 14, 5)
    assert stamp_pdf.format_date(d, "DD MMM YYYY") == "09 JUL 2026"
    assert stamp_pdf.format_date(d, "DD/MM/YYYY") == "09/07/2026"
    assert stamp_pdf.format_date(d, "YYYY-MM-DD", True) == "2026-07-09 14:05 MYT"
    ids = {stamp_store._new_document_id() for _ in range(500)}
    assert len(ids) == 500
    assert all(re.fullmatch(r"CNC-\d{8}-[A-HJ-NP-Z2-9]{6}", i) for i in ids)


# --- permissions --------------------------------------------------------------

def test_requires_login(app_client):
    anon = TestClient(main.app)
    assert anon.get("/api/stamp/overview").status_code == 401
    assert anon.get("/api/stamp/documents").status_code == 401
    assert upload(anon).status_code == 401
    assert anon.get("/document-centre", follow_redirects=False).status_code == 302
    assert anon.get("/verify").status_code == 200


def test_wrong_password_rejected_and_audited(app_client, boss):
    r = TestClient(main.app).post("/api/login", json={"username": "boss", "password": "not-it"})
    assert r.status_code == 401
    assert any(e["event_type"] == "LOGIN_FAILED" for e in boss.get("/api/stamp/audit").json())


def test_viewer_is_read_only_and_has_no_finance_access(reader, staff):
    assert upload(reader).status_code == 403
    assert reader.get("/api/state").status_code == 403
    assert reader.get("/api/transactions").status_code == 403
    assert reader.get("/api/stamp/config").json()["stamps"] == []
    done = stamp(staff)
    draft = upload(staff).json()
    listed = [d["document_id"] for d in reader.get("/api/stamp/documents").json()]
    assert done["document_id"] in listed and draft["document_id"] not in listed
    assert reader.get(f"/api/stamp/documents/{done['document_id']}/download").status_code == 200
    assert reader.get(f"/api/stamp/documents/{done['document_id']}/file").status_code == 403
    assert reader.get(f"/api/stamp/documents/{draft['document_id']}").status_code == 403


def test_stamper_cannot_administer(staff):
    assert staff.get("/api/stamp/audit").status_code == 403
    assert staff.get("/api/stamp/settings").status_code == 403
    assert staff.put("/api/stamp/settings", json={"qr_enabled": True}, headers=ORIGIN).status_code == 403
    assert staff.post("/api/stamp/stamps", params={"name": "X", "kind": "text", "text": "X"},
                      headers=ORIGIN).status_code == 403
    doc = stamp(staff)
    assert staff.post(f"/api/stamp/documents/{doc['document_id']}/void", json={"reason": "oops"},
                      headers=ORIGIN).status_code == 403


def test_documents_are_private_between_stampers(staff, staff2):
    doc = upload(staff).json()
    assert staff2.get(f"/api/stamp/documents/{doc['document_id']}").status_code == 403
    assert staff2.post(f"/api/stamp/documents/{doc['document_id']}/finalize",
                       json={"items": [item(chop_id(staff2))]}, headers=ORIGIN).status_code == 403


def test_restricted_stamp_cannot_be_used(boss, staff):
    r = boss.post("/api/stamp/stamps", params={"name": "Director Only", "kind": "text",
                  "text": "DIRECTOR", "roles": "director"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert sid not in [s["id"] for s in staff.get("/api/stamp/config").json()["stamps"]]
    doc = upload(staff).json()
    r = staff.post(f"/api/stamp/documents/{doc['document_id']}/finalize",
                   json={"items": [item(sid)]}, headers=ORIGIN)
    assert r.status_code == 403
    assert staff.get(f"/api/stamp/documents/{doc['document_id']}").json()["status"] == "DRAFT"


def test_cross_site_write_refused(staff):
    r = staff.post("/api/stamp/documents", params={"filename": "a.pdf"}, content=make_pdf(),
                   headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_signature_is_private(staff, staff2):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (300, 120), (0, 0, 0, 0))
    ImageDraw.Draw(img).line([(10, 100), (120, 20), (290, 90)], fill=(10, 10, 120, 255), width=5)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    assert staff.post("/api/stamp/signature", content=buf.getvalue(), headers=ORIGIN).status_code == 200
    assert staff.get("/api/stamp/signature/image").status_code == 200
    assert staff2.get("/api/stamp/signature/image").status_code == 404   # staff2 has none of their own
    doc = upload(staff2).json()
    r = staff2.post(f"/api/stamp/documents/{doc['document_id']}/finalize", headers=ORIGIN,
                    json={"items": [{**item(None), "kind": "signature"}]})
    assert r.status_code == 400 and "signature" in r.json()["detail"].lower()
    # and staff's own signature stamps fine
    doc = upload(staff).json()
    r = staff.post(f"/api/stamp/documents/{doc['document_id']}/finalize", headers=ORIGIN,
                   json={"items": [{**item(None), "kind": "signature"}]})
    assert r.status_code == 200, r.text


# --- upload validation --------------------------------------------------------

def test_upload_rejects_non_pdf_and_corrupt(staff):
    assert upload(staff, b"MZ\x90\x00 this is not a pdf at all" * 20, "invoice.pdf").status_code == 400
    assert upload(staff, b"%PDF-1.7\n garbage garbage garbage" * 10).status_code == 400
    assert upload(staff, b"").status_code == 400


def test_upload_rejects_encrypted(staff):
    w = PdfWriter()
    w.append(PdfReader(io.BytesIO(make_pdf(1))))
    w.encrypt("secret")
    out = io.BytesIO()
    w.write(out)
    r = upload(staff, out.getvalue())
    assert r.status_code == 400 and "password" in r.json()["detail"].lower()


def test_upload_rejects_oversize(staff, boss):
    boss.put("/api/stamp/settings", json={"max_upload_mb": 1}, headers=ORIGIN)
    try:
        assert upload(staff, make_pdf(1) + b"\n%" + b"x" * (1024 * 1024 + 10)).status_code == 413
    finally:
        boss.put("/api/stamp/settings", json={"max_upload_mb": 20}, headers=ORIGIN)


def test_filename_is_sanitised_and_never_a_path(staff):
    d = upload(staff, name="..\\..\\evil/../../x<y>.pdf").json()
    assert d["original_filename"] == "xy.pdf"
    row = stamp_store.get_document(d["document_id"])
    assert re.fullmatch(r"[a-f0-9]{32}\.pdf", row["original_file_key"])


# --- generation, hashes, verification -----------------------------------------

def test_stamp_flow_hashes_and_download(staff):
    original = make_pdf(3)
    up = upload(staff, original).json()
    assert re.fullmatch(r"CNC-\d{8}-[A-Z0-9]{6}", up["document_id"]) and up["status"] == "DRAFT"
    assert up["original_sha256"] == stamp_pdf.sha256_hex(original)
    did = up["document_id"]
    assert staff.post(f"/api/stamp/documents/{did}/finalize", json={"items": []},
                      headers=ORIGIN).status_code == 400
    items = [item(chop_id(staff), pages="1,3"),
             {**item(None), "kind": "date", "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.03},
             {**item(None), "kind": "text", "text": "FOR INTERNAL USE", "x": 0.1, "y": 0.2,
              "w": 0.4, "h": 0.06, "rotation": 15}]
    summary = staff.post(f"/api/stamp/documents/{did}/preview-summary", json={"items": items},
                         headers=ORIGIN).json()
    assert summary["pages"] == [1, 3] and summary["signed_by"] == "staff"
    done = staff.post(f"/api/stamp/documents/{did}/finalize", json={"items": items}, headers=ORIGIN).json()
    assert done["status"] == "COMPLETED" and done["final_sha256"] != done["original_sha256"]

    r = staff.get(f"/api/stamp/documents/{did}/download")
    assert r.headers["content-disposition"] == f'attachment; filename="{did}_Stamped.pdf"'
    final = r.content
    assert stamp_pdf.sha256_hex(final) == done["final_sha256"]          # stored hash is of the exact bytes served
    reader = PdfReader(io.BytesIO(final))
    assert len(reader.pages) == 3
    assert all("/Annots" not in p for p in reader.pages)                # flattened, not annotations
    assert "page 2" in reader.pages[1].extract_text()                   # original content untouched
    assert stamp_pdf.embedded_document_id(final) == did
    # the original is kept byte-for-byte and never overwritten
    assert staff.get(f"/api/stamp/documents/{did}/file").content == original
    # a finished document cannot be stamped again
    assert staff.post(f"/api/stamp/documents/{did}/finalize", json={"items": items},
                      headers=ORIGIN).status_code == 409
    events = [e["event_type"] for e in staff.get(f"/api/stamp/documents/{did}/audit").json()]
    assert {"DOCUMENT_UPLOADED", "DOCUMENT_STAMPED", "DOCUMENT_DOWNLOADED"} <= set(events)


@pytest.mark.parametrize("rotate", [90, 180, 270])
def test_rotated_pages_generate(staff, rotate):
    doc = upload(staff, make_pdf(2, rotate=rotate)).json()
    r = staff.post(f"/api/stamp/documents/{doc['document_id']}/finalize",
                   json={"items": [item(chop_id(staff), pages="all", rotation=30, opacity=0.6)]},
                   headers=ORIGIN)
    assert r.status_code == 200, r.text


def test_invalid_page_selection(staff):
    doc = upload(staff).json()
    r = staff.post(f"/api/stamp/documents/{doc['document_id']}/finalize",
                   json={"items": [item(chop_id(staff), pages="2,9")]}, headers=ORIGIN)
    assert r.status_code == 400 and "page selection" in r.json()["detail"].lower()


def test_verify_match_mismatch_notfound(staff):
    done = stamp(staff)
    did = done["document_id"]
    final = staff.get(f"/api/stamp/documents/{did}/download").content
    anon = TestClient(main.app)

    ok = anon.post("/api/verify", content=final).json()
    assert ok["status"] == "VERIFIED" and ok["document_id"] == did
    assert ok["message"] == "Document matches the registered stamped file."
    # nothing private leaks to the public
    assert not ({"created_by_name", "original_filename", "filename", "ip_address",
                 "original_file_key", "final_file_key", "created_by"} & set(ok))
    assert "staff" not in str(ok)

    altered = final + b"\n% one extra byte changes everything\n"
    bad = anon.post("/api/verify", content=altered).json()
    assert bad["status"] == "MISMATCH" and "does not match" in bad["message"]

    assert anon.post("/api/verify", content=make_pdf(1, text="Unrelated")).json()["status"] == "NOT_FOUND"
    assert anon.post("/api/verify", content=b"not a pdf at all, definitely" * 10).status_code == 400
    assert anon.get(f"/api/verify/{did}").json()["status"] == "REGISTERED"
    assert anon.get("/api/verify/CNC-20260101-ZZZZZZ").json()["status"] == "NOT_FOUND"
    assert anon.get("/api/verify/whatever").json()["status"] == "NOT_FOUND"
    # the original (unstamped) upload is not the registered file
    assert anon.post("/api/verify", content=make_pdf()).json()["status"] == "NOT_FOUND"


def test_drafts_are_not_publicly_registered(staff):
    d = upload(staff).json()
    assert TestClient(main.app).get(f"/api/verify/{d['document_id']}").json()["status"] == "NOT_FOUND"


def test_void(staff, boss):
    done = stamp(staff)
    did = done["document_id"]
    final = staff.get(f"/api/stamp/documents/{did}/download").content
    assert boss.post(f"/api/stamp/documents/{did}/void", json={"reason": ""},
                     headers=ORIGIN).status_code == 422
    r = boss.post(f"/api/stamp/documents/{did}/void", json={"reason": "Issued in error"}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["status"] == "VOID"
    anon = TestClient(main.app)
    for res in (anon.get(f"/api/verify/{did}").json(), anon.post("/api/verify", content=final).json()):
        assert res["status"] == "VOID" and "marked void" in res["message"]
    assert stamp_store.get_document(did)["final_sha256"] == done["final_sha256"]   # record kept
    assert "DOCUMENT_VOIDED" in [e["event_type"]
                                 for e in boss.get(f"/api/stamp/documents/{did}/audit").json()]


def test_qr_and_footer_are_part_of_the_hashed_file(staff, boss):
    boss.put("/api/stamp/settings", json={"qr_enabled": True, "footer_enabled": True}, headers=ORIGIN)
    try:
        done = stamp(staff)
    finally:
        boss.put("/api/stamp/settings", json={"qr_enabled": False, "footer_enabled": False}, headers=ORIGIN)
    final = staff.get(f"/api/stamp/documents/{done['document_id']}/download").content
    assert stamp_pdf.sha256_hex(final) == done["final_sha256"]
    assert done["document_id"] in PdfReader(io.BytesIO(final)).pages[0].extract_text()
    assert TestClient(main.app).post("/api/verify", content=final).json()["status"] == "VERIFIED"


def test_audit_log_is_append_only(app_client):
    stamp_store.audit("TEST_EVENT")
    with pytest.raises(Exception):
        with storage.get_conn() as conn:
            conn.execute("UPDATE stamp_audit SET event_type = 'X'")
    with pytest.raises(Exception):
        with storage.get_conn() as conn:
            conn.execute("DELETE FROM stamp_audit")


def test_wording_never_overclaims():
    import pathlib
    root = pathlib.Path(main.__file__).resolve().parent.parent
    banned = ["legally certified", "government verified", "lhdn approved", "ssm verified",
              "qualified digital signature", "official digital certificate"]
    for f in [root / "frontend" / "document-centre.html", root / "frontend" / "verify.html"]:
        if f.exists():
            text = f.read_text(encoding="utf-8").lower()
            assert not [b for b in banned if b in text], f.name
