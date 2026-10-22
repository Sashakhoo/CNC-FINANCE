"""
PDF engine for the Document Centre: validate an uploaded PDF, and burn
stamps / signatures / text into the real page content.

Coordinates
-----------
The editor in the browser works in "what you see" terms: each placement is a
box given as FRACTIONS of the page as displayed (x, y from the top-left
corner, y pointing down), plus a clockwise rotation in degrees. That is
independent of zoom and screen size.

A PDF page is a different world: its origin is bottom-left with y pointing
up, the visible area is the CropBox (which need not start at 0,0), and the
page may carry a /Rotate of 90/180/270 that viewers apply before showing it.
`display_matrix()` is the single place that maps between the two, and
`placement_rect()` exposes the result for tests.

Flattening
----------
Stamps are drawn into a one-page overlay and merged into the page's content
stream (pypdf merge_page). They are not annotations, so a PDF reader can't
select and move them. Pages are never rasterised - the original text and
vector quality are untouched.
"""
import hashlib
import io
import re
from datetime import datetime, timezone

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from pypdf.generic import NameObject
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas

FONT = "Helvetica-Bold"
MAX_PAGES = 500
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
DATE_FORMATS = ["DD MMM YYYY", "DD/MM/YYYY", "YYYY-MM-DD"]

# Text stamps share these proportions with the editor's SVG preview
# (frontend/document-centre.html: textGeometry) so the two always agree.
TEXT_FONT_RATIO = 0.50      # font size as a fraction of the box height (bordered stamps)
TEXT_FIT_RATIO = 0.86       # text may use this much of the box width
DATE_FONT_RATIO = 0.72      # plain text (dates) fill more of the box
DATE_FIT_RATIO = 0.98
BORDER_RATIO = 0.06         # border thickness as a fraction of the box height
CAP_HEIGHT = 0.718          # Helvetica-Bold cap height, for vertical centring


class StampError(Exception):
    """A problem the user can be told about (message is safe to show)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- validation ----------------------------------------------------------

def open_pdf(data: bytes, max_bytes: int = None) -> PdfReader:
    """Reject anything that is not a real, readable, unencrypted PDF.
    The file's name and declared MIME type are never trusted - only its bytes."""
    if max_bytes and len(data) > max_bytes:
        raise StampError(f"File is larger than the {max_bytes // (1024 * 1024)} MB limit.", 413)
    if len(data) < 100 or b"%PDF-" not in data[:1024]:
        raise StampError("Only PDF files can be uploaded.")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise StampError("Document is password protected. Remove the password and upload it again.")
        count = len(reader.pages)
        if count < 1:
            raise StampError("PDF could not be processed.")
        if count > MAX_PAGES:
            raise StampError(f"PDF has too many pages (limit {MAX_PAGES}).")
        for page in reader.pages:           # touching every page surfaces a broken page tree now
            _ = page.cropbox
        return reader
    except StampError:
        raise
    except (PdfReadError, Exception):
        raise StampError("PDF could not be processed.")


def page_sizes(reader: PdfReader) -> list:
    """Displayed (width, height) in points for every page."""
    out = []
    for page in reader.pages:
        _, _, w, h, _ = _page_geometry(page)
        out.append({"w": round(w, 2), "h": round(h, 2)})
    return out


def _page_geometry(page):
    box = page.cropbox
    x0, y0, x1, y1 = float(box.left), float(box.bottom), float(box.right), float(box.top)
    rotation = int(page.rotation or 0) % 360
    if rotation not in (0, 90, 180, 270):
        rotation = 0
    cw, ch = x1 - x0, y1 - y0
    disp_w, disp_h = (cw, ch) if rotation in (0, 180) else (ch, cw)
    return (x0, y0, x1, y1), rotation, disp_w, disp_h, (cw, ch)


def display_matrix(cropbox, rotation: int) -> tuple:
    """Affine matrix (a, b, c, d, e, f) taking a point in DISPLAY space -
    origin at the bottom-left of the page as shown, y up, in points - to the
    page's own unrotated user space:  x' = a*x + c*y + e,  y' = b*x + d*y + f."""
    x0, y0, x1, y1 = cropbox
    if rotation == 90:
        return (0, 1, -1, 0, x1, y0)
    if rotation == 180:
        return (-1, 0, 0, -1, x1, y1)
    if rotation == 270:
        return (0, -1, 1, 0, x0, y1)
    return (1, 0, 0, 1, x0, y0)


def _apply(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def placement_rect(cropbox, rotation: int, x: float, y: float, w: float, h: float) -> dict:
    """Where an (unrotated) browser placement lands in PDF user space.
    Returns the centre point and the axis-aligned bounding box."""
    x0, y0, x1, y1 = cropbox
    cw, ch = x1 - x0, y1 - y0
    disp_w, disp_h = (cw, ch) if rotation in (0, 180) else (ch, cw)
    m = display_matrix(cropbox, rotation)
    left, top = x * disp_w, y * disp_h
    pw, ph = w * disp_w, h * disp_h
    corners = [_apply(m, left, disp_h - top), _apply(m, left + pw, disp_h - top),
               _apply(m, left, disp_h - top - ph), _apply(m, left + pw, disp_h - top - ph)]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    return {"center": _apply(m, left + pw / 2, disp_h - top - ph / 2),
            "bbox": (min(xs), min(ys), max(xs), max(ys))}


# --- page selection --------------------------------------------------------

def parse_pages(spec: str, page_count: int, current: int = 1) -> list:
    """'current' | 'all' | 'first' | 'last' | '1,3,5-8'  ->  sorted 1-based page numbers."""
    spec = (spec or "current").strip().lower()
    if spec == "current":
        pages = [current]
    elif spec == "all":
        pages = list(range(1, page_count + 1))
    elif spec == "first":
        pages = [1]
    elif spec == "last":
        pages = [page_count]
    else:
        if spec.startswith("custom:"):
            spec = spec[7:]
        if not re.fullmatch(r"[\d\s,\-]+", spec or ""):
            raise StampError("Invalid page selection.")
        found = set()
        for part in [p.strip() for p in spec.split(",") if p.strip()]:
            if "-" in part:
                a, _, b = part.partition("-")
                if not a.strip().isdigit() or not b.strip().isdigit():
                    raise StampError("Invalid page selection.")
                lo, hi = int(a), int(b)
                if lo > hi:
                    raise StampError("Invalid page selection.")
                found.update(range(lo, hi + 1))
            elif part.isdigit():
                found.add(int(part))
            else:
                raise StampError("Invalid page selection.")
        pages = sorted(found)
        if not pages:
            raise StampError("Invalid page selection.")
    if any(p < 1 or p > page_count for p in pages):
        raise StampError(f"Invalid page selection. This document has {page_count} page(s).")
    return pages


# --- dates (server clock only) --------------------------------------------

def format_date(now: datetime, fmt: str, with_time: bool = False, tz_label: str = "MYT") -> str:
    if fmt == "DD/MM/YYYY":
        out = now.strftime("%d/%m/%Y")
    elif fmt == "YYYY-MM-DD":
        out = now.strftime("%Y-%m-%d")
    else:
        out = f"{now.day:02d} {MONTHS[now.month - 1]} {now.year}"
    if with_time:
        out += f" {now.strftime('%H:%M')} {tz_label}"
    return out


# --- drawing -----------------------------------------------------------------

def text_layout(text: str, box_w: float, box_h: float, border: bool) -> dict:
    """Font size and horizontal squeeze for a text stamp in a box (points)."""
    size = box_h * (TEXT_FONT_RATIO if border else DATE_FONT_RATIO)
    natural = stringWidth(text, FONT, size) or 1
    avail = box_w * (TEXT_FIT_RATIO if border else DATE_FIT_RATIO)
    return {"size": size, "scale": min(1.0, avail / natural), "width": min(natural, avail)}


def _draw_text(c, text, color, pw, ph, border):
    lay = text_layout(text, pw, ph, border)
    _fill(c, color)
    _stroke(c, color)
    if border:
        lw = ph * BORDER_RATIO
        c.setLineWidth(lw)
        c.roundRect(-pw / 2 + lw / 2, -ph / 2 + lw / 2, pw - lw, ph - lw, ph * 0.10, stroke=1, fill=0)
    t = c.beginText()
    t.setFont(FONT, lay["size"])
    t.setHorizScale(lay["scale"] * 100)
    t.setTextOrigin(-lay["width"] / 2, -lay["size"] * CAP_HEIGHT / 2)
    t.textOut(text)
    c.drawText(t)


def _safe_color(value: str, default: str = "#16168a"):
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value or ""):
        value = default
    return HexColor(value)


# --- editor elements (text, shapes, freehand) ----------------------------------
# Every constant here is mirrored in frontend/document-centre.html so the
# on-screen preview and the PDF agree. Sizes are fractions of the displayed
# page HEIGHT, so they scale with the page like everything else.

FONTS = {   # regular, bold, italic, bold-italic, first-baseline factor
    "helv": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique", 0.95),
    "times": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic", 0.94),
    "courier": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique", 0.87),
}
LINE_HEIGHT = 1.2
SHAPES = ("rect", "ellipse", "line", "arrow", "check", "cross", "dot",
          "whiteout", "highlight", "strike", "underline")
SYMBOL_STROKE = 0.12          # tick / cross line width, fraction of the smaller box side
CHECK_POINTS = [(0.08, 0.55), (0.38, 0.85), (0.92, 0.15)]


def font_for(font: str, bold: bool, italic: bool) -> tuple:
    f = FONTS.get(font) or FONTS["helv"]
    return f[(1 if bold else 0) + (2 if italic else 0)], f[4]


def _draw_plain(c, it, pw, ph, disp_h):
    """Left-aligned, multi-line text anchored at the box's top-left corner."""
    size = float(it["fs"]) * disp_h
    name, base = font_for(it.get("font"), it.get("bold"), it.get("italic"))
    _fill(c, _safe_color(it.get("color"), "#15141a"))
    c.setFont(name, size)
    top, left = ph / 2, -pw / 2
    for i, line in enumerate(str(it.get("text", "")).split("\n")):
        if line:
            c.drawString(left, top - size * (base + LINE_HEIGHT * i), line)


def _fill(c, color):
    c.setFillColor(color)
    c.setFillAlpha(getattr(c, "_cnc_alpha", 1))


def _stroke(c, color):
    c.setStrokeColor(color)
    c.setStrokeAlpha(getattr(c, "_cnc_alpha", 1))


def _local(fx, fy, pw, ph):
    """Box fractions (origin top-left, y down) -> centred local coords (y up)."""
    return (fx - 0.5) * pw, (0.5 - fy) * ph


def _draw_shape(c, it, pw, ph, disp_h):
    shape = it.get("shape")
    stroke = _safe_color(it.get("stroke"), "#15141a")
    sw = max(0.2, float(it.get("sw") or 0.002) * disp_h)
    fill = it.get("fill")
    c.setLineCap(1)
    c.setLineJoin(1)
    _stroke(c, stroke)
    c.setLineWidth(sw)
    if shape == "whiteout":
        _fill(c, HexColor("#ffffff"))
        c.rect(-pw / 2, -ph / 2, pw, ph, stroke=0, fill=1)
    elif shape == "highlight":
        _fill(c, _safe_color(it.get("fill"), "#ffe14d"))
        c.rect(-pw / 2, -ph / 2, pw, ph, stroke=0, fill=1)
    elif shape in ("rect", "ellipse"):
        has_fill = bool(fill)
        if has_fill:
            _fill(c, _safe_color(fill, "#ffffff"))
        if shape == "rect":
            c.rect(-pw / 2 + sw / 2, -ph / 2 + sw / 2, max(pw - sw, 0.1), max(ph - sw, 0.1), stroke=1, fill=int(has_fill))
        else:
            c.ellipse(-pw / 2 + sw / 2, -ph / 2 + sw / 2, pw / 2 - sw / 2, ph / 2 - sw / 2, stroke=1, fill=int(has_fill))
    elif shape in ("line", "strike"):
        c.line(-pw / 2, 0, pw / 2, 0)
    elif shape == "underline":
        c.line(-pw / 2, -ph / 2 + sw / 2, pw / 2, -ph / 2 + sw / 2)
    elif shape == "arrow":
        hs = max(sw * 4, 6)
        c.line(-pw / 2, 0, pw / 2 - hs * 0.8, 0)
        _fill(c, stroke)
        path = c.beginPath()
        path.moveTo(pw / 2, 0)
        path.lineTo(pw / 2 - hs, hs * 0.55)
        path.lineTo(pw / 2 - hs, -hs * 0.55)
        path.close()
        c.drawPath(path, stroke=0, fill=1)
    elif shape == "check":
        c.setLineWidth(SYMBOL_STROKE * min(pw, ph))
        path = c.beginPath()
        for i, (fx, fy) in enumerate(CHECK_POINTS):
            x, y = _local(fx, fy, pw, ph)
            path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
        c.drawPath(path, stroke=1, fill=0)
    elif shape == "cross":
        c.setLineWidth(SYMBOL_STROKE * min(pw, ph))
        for (a, b), (d, e) in (((0.15, 0.15), (0.85, 0.85)), ((0.85, 0.15), (0.15, 0.85))):
            c.line(*_local(a, b, pw, ph), *_local(d, e, pw, ph))
    elif shape == "dot":
        _fill(c, stroke)
        c.circle(0, 0, 0.35 * min(pw, ph), stroke=0, fill=1)


def _draw_ink(c, it, pw, ph, disp_h):
    pts = it.get("points") or []
    if len(pts) < 2:
        return
    c.setLineCap(1)
    c.setLineJoin(1)
    _stroke(c, _safe_color(it.get("stroke"), "#15141a"))
    c.setLineWidth(max(0.2, float(it.get("sw") or 0.002) * disp_h))
    path = c.beginPath()
    for i, (fx, fy) in enumerate(pts):
        x, y = _local(fx, fy, pw, ph)
        path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
    c.drawPath(path, stroke=1, fill=0)


# --- existing PDF form fields ---------------------------------------------------
# Fields are read from the original so the editor can show them as inputs. On
# export the values are drawn as ordinary page content and the interactive
# widgets are removed, so the registered copy is flat and can't be re-typed.

def _inherited(obj, key):
    seen = 0
    while obj is not None and seen < 20:
        if key in obj:
            return obj[key]
        obj = obj.get("/Parent")
        obj = obj.get_object() if obj is not None else None
        seen += 1
    return None


def _full_name(obj) -> str:
    parts, seen = [], 0
    while obj is not None and seen < 20:
        if "/T" in obj:
            parts.append(str(obj["/T"]))
        obj = obj.get("/Parent")
        obj = obj.get_object() if obj is not None else None
        seen += 1
    return ".".join(reversed(parts))


def _to_display(page, rect) -> tuple:
    """PDF user-space rect -> (x, y, w, h) as fractions of the displayed page."""
    cropbox, rotation, disp_w, disp_h, _ = _page_geometry(page)
    a, b, c, d, e, f = display_matrix(cropbox, rotation)
    det = a * d - b * c
    xs, ys = [], []
    x0, y0, x1, y1 = [float(v) for v in rect]
    for px, py in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        px, py = px - e, py - f
        dx = (d * px - c * py) / det
        dy = (-b * px + a * py) / det
        xs.append(dx); ys.append(dy)
    left, right, bottom, top = min(xs), max(xs), min(ys), max(ys)
    return left / disp_w, 1 - top / disp_h, (right - left) / disp_w, (top - bottom) / disp_h


def form_fields(reader) -> list:
    """[{name, type: text|checkbox|radio|choice, page, x, y, w, h, value, export, options, multiline}]"""
    out = []
    for number, page in enumerate(reader.pages, 1):
        annots = page.get("/Annots")
        if not annots:
            continue
        try:
            annots = annots.get_object()
        except Exception:
            continue
        for ref in annots:
            try:
                w = ref.get_object()
                if w.get("/Subtype") != "/Widget":
                    continue
                ft = _inherited(w, "/FT")
                name = _full_name(w)
                if not name or ft not in ("/Tx", "/Btn", "/Ch"):
                    continue
                flags = int(_inherited(w, "/Ff") or 0)
                value = _inherited(w, "/V")
                x, y, wd, ht = _to_display(page, w["/Rect"])
                field = {"name": name[:200], "page": number, "x": x, "y": y, "w": wd, "h": ht}
                if ft == "/Tx":
                    field.update(type="text", value=str(value or ""), multiline=bool(flags & 4096))
                elif ft == "/Ch":
                    opts = []
                    for o in (_inherited(w, "/Opt") or []):
                        o = o.get_object() if hasattr(o, "get_object") else o
                        opts.append(str(o[-1] if isinstance(o, (list, tuple)) else o))
                    field.update(type="choice", value=str(value or ""), options=opts[:200])
                else:
                    if flags & 65536:            # push button - nothing to fill
                        continue
                    states = [str(k) for k in (w.get("/AP", {}).get("/N", {}) or {}).keys() if str(k) != "/Off"]
                    export = states[0][1:] if states else "Yes"
                    kind = "radio" if flags & 32768 else "checkbox"
                    current = str(value or "")[1:] if value else ""
                    if kind == "checkbox" and not current and str(w.get("/AS", "/Off")) != "/Off":
                        current = export
                    field.update(type=kind, value=current, export=export)
                out.append(field)
            except Exception:
                continue
    return out


def field_placements(fields: list, values: dict) -> list:
    """Turn filled form values into ordinary placements (drawn, not interactive)."""
    out = []
    for f in fields:
        v = values.get(f["name"], f.get("value", ""))
        v = "" if v is None else str(v)
        base = {"page": f["page"], "x": f["x"], "y": f["y"], "w": f["w"], "h": f["h"],
                "rotation": 0, "opacity": 1}
        if f["type"] in ("text", "choice"):
            if not v.strip():
                continue
            lines = v.split("\n") if f.get("multiline") else [v.replace("\n", " ")]
            fs = min(f["h"] * (0.62 if len(lines) == 1 else 0.85 / max(len(lines), 1) / LINE_HEIGHT), 11 / 842)
            pad_y = 0 if len(lines) > 1 else max(0.0, (f["h"] - fs * LINE_HEIGHT) / 2)
            out.append({**base, "kind": "plain", "text": "\n".join(lines), "font": "helv",
                        "fs": fs, "color": "#15141a", "y": f["y"] + pad_y, "x": f["x"] + 2 / 595})
        elif f["type"] == "checkbox" and v and v != "Off":
            out.append({**base, "kind": "shape", "shape": "check", "stroke": "#15141a"})
        elif f["type"] == "radio" and v and v == f.get("export"):
            out.append({**base, "kind": "shape", "shape": "dot", "stroke": "#15141a"})
    return out


def _remove_form(writer):
    for page in writer.pages:
        annots = page.get("/Annots")
        if not annots:
            continue
        keep = [a for a in annots.get_object() if a.get_object().get("/Subtype") != "/Widget"]
        if keep:
            from pypdf.generic import ArrayObject
            page[NameObject("/Annots")] = ArrayObject(keep)
        else:
            del page["/Annots"]
    root = writer._root_object
    if "/AcroForm" in root:
        del root["/AcroForm"]


def _add_links(writer, links: list):
    from pypdf.annotations import Link
    for ln in links:
        page = writer.pages[ln["page"] - 1]
        cropbox, rotation, _, _, _ = _page_geometry(page)
        bbox = placement_rect(cropbox, rotation, ln["x"], ln["y"], ln["w"], ln["h"])["bbox"]
        writer.add_annotation(ln["page"] - 1, Link(rect=bbox, url=ln["url"]))


def _overlay_for_page(page, items: list, images: dict):
    cropbox, rotation, disp_w, disp_h, _ = _page_geometry(page)
    media = page.mediabox
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(max(float(media.right), 1), max(float(media.top), 1)),
                         pageCompression=1)
    c.transform(*display_matrix(cropbox, rotation))      # from here on we draw in display space
    for it in items:
        pw, ph = it["w"] * disp_w, it["h"] * disp_h
        cx = it["x"] * disp_w + pw / 2
        cy = disp_h - (it["y"] * disp_h + ph / 2)
        opacity = max(0.05, min(1.0, float(it.get("opacity", 1))))
        c.saveState()
        c.translate(cx, cy)
        c.rotate(-float(it.get("rotation", 0)))           # browser angles are clockwise
        c.setFillAlpha(opacity)
        c.setStrokeAlpha(opacity)
        c._cnc_alpha = opacity
        kind = it["kind"]
        if kind == "image":
            c.drawImage(images[it["image"]], -pw / 2, -ph / 2, pw, ph, mask="auto")
        elif kind == "plain":
            _draw_plain(c, it, pw, ph, disp_h)
        elif kind == "shape":
            _draw_shape(c, it, pw, ph, disp_h)
        elif kind == "ink":
            _draw_ink(c, it, pw, ph, disp_h)
        else:
            _draw_text(c, it["text"], _safe_color(it.get("color")), pw, ph, bool(it.get("border", True)))
        c.restoreState()
    c.showPage()
    c.save()
    return PdfReader(io.BytesIO(buf.getvalue())).pages[0]


def render(original: bytes, placements: list, images: dict, *, document_id: str,
           footer_text: str = None, qr_png: bytes = None, qr_position: str = "bottom-right",
           company: str = "", appendix: bytes = None, field_values: dict = None,
           links: list = None) -> bytes:
    """Build the final stamped PDF.

    placements: [{kind:'image'|'text', page (1-based), x, y, w, h (fractions of the
                 displayed page), rotation, opacity, image (key into `images`) | text, color, border}]
    images:     {key: PNG bytes}

    Everything visible (stamps, footer, QR) is added here, before the caller
    hashes the result - nothing may touch the bytes afterwards."""
    reader = open_pdf(original)
    fields = form_fields(reader)
    placements = list(placements) + field_placements(fields, field_values or {})
    writer = PdfWriter(clone_from=reader)
    if fields:
        _remove_form(writer)
    if appendix:                       # e.g. the e-signature certificate page
        for extra in PdfReader(io.BytesIO(appendix)).pages:
            writer.add_page(extra)
    readers = {k: ImageReader(io.BytesIO(v)) for k, v in images.items()}
    if qr_png:
        readers["__qr__"] = ImageReader(io.BytesIO(qr_png))

    by_page = {}
    for p in placements:
        by_page.setdefault(int(p["page"]), []).append(p)

    page_count = len(writer.pages)
    for number in range(1, page_count + 1):
        page = writer.pages[number - 1]
        items = list(by_page.get(number, []))
        _, _, disp_w, disp_h, _ = _page_geometry(page)
        if footer_text:
            fh = 7.5 / disp_h
            fw = min(0.9, stringWidth(footer_text, FONT, 7.5 * DATE_FONT_RATIO) / DATE_FIT_RATIO / disp_w)
            items.append({"kind": "text", "text": footer_text, "color": "#6b6b78", "border": False,
                          "x": 24 / disp_w, "y": 1 - (14 / disp_h) - fh, "w": fw, "h": fh,
                          "rotation": 0, "opacity": 1})
        if qr_png and number == page_count:
            size, margin = 54.0, 22.0
            qx = margin if "left" in qr_position else disp_w - margin - size
            qy = margin if "top" in qr_position else disp_h - margin - size
            items.append({"kind": "image", "image": "__qr__", "x": qx / disp_w, "y": qy / disp_h,
                          "w": size / disp_w, "h": size / disp_h, "rotation": 0, "opacity": 1})
        if items:
            page.merge_page(_overlay_for_page(page, items, readers))

    if links:
        _add_links(writer, links)
    _strip_active_content(writer)
    writer.add_metadata({
        "/Producer": "CNC Document Centre",
        "/CNCDocumentID": document_id,
        "/CNCRegisteredBy": company,
        "/ModDate": datetime.now(timezone.utc).strftime("D:%Y%m%d%H%M%S+00'00'"),
    })
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _mask_ip(ip: str) -> str:
    ip = (ip or "").strip()
    if ip.count(".") == 3:
        return ".".join(ip.split(".")[:3]) + ".x"
    if ":" in ip:
        return ":".join(ip.split(":")[:3]) + ":..."
    return ip or "-"


def certificate_pdf(info: dict) -> bytes:
    """One A4 page recording how and when each electronic signature was given.
    info: {document_id, filename, original_sha256, company, registration, sent_by,
           sent_at, completed_at, signers: [{name, contact, signed_at, ip, user_agent}]}"""
    buf = io.BytesIO()
    W, H = 595.28, 841.89
    c = rl_canvas.Canvas(buf, pagesize=(W, H), pageCompression=1)
    ink, dim = HexColor("#15141a"), HexColor("#6b6b78")
    x0, y = 56, H - 64

    def line(label, value, size=9.5, gap=16, mono=False):
        nonlocal y
        c.setFont("Helvetica", 8); c.setFillColor(dim); c.drawString(x0, y, label.upper())
        c.setFont("Courier" if mono else "Helvetica", size); c.setFillColor(ink)
        text = str(value or "-")
        width = W - x0 - 56 - 130
        while text:                                  # simple wrap for long hashes / names
            n = len(text)
            while n > 1 and stringWidth(text[:n], "Courier" if mono else "Helvetica", size) > width:
                n -= 1
            c.drawString(x0 + 130, y, text[:n]); text = text[n:]
            if text:
                y -= size + 3
        y -= gap

    c.setFont("Helvetica-Bold", 17); c.setFillColor(ink)
    c.drawString(x0, y, "Signature Certificate"); y -= 18
    c.setFont("Helvetica", 9); c.setFillColor(dim)
    c.drawString(x0, y, f"Electronic signatures collected through the {info.get('company', '')} Document Centre.")
    y -= 30
    line("Document ID", info.get("document_id"), mono=True)
    line("File", info.get("filename"))
    line("Original SHA-256", info.get("original_sha256"), size=8, mono=True)
    line("Sent for signature", f"{info.get('sent_by')} - {info.get('sent_at')}")
    line("Completed", info.get("completed_at"))
    y -= 6
    for i, s in enumerate(info.get("signers", []), 1):
        if y < 150:
            break
        c.setStrokeColor(HexColor("#eae6db")); c.setLineWidth(0.8); c.line(x0, y + 8, W - 56, y + 8)
        y -= 10
        c.setFont("Helvetica-Bold", 11); c.setFillColor(ink); c.drawString(x0, y, f"Signer {i}: {s.get('name')}")
        y -= 20
        if s.get("contact"):
            line("Contact", s.get("contact"))
        line("Signed at", s.get("signed_at"))
        line("IP address", _mask_ip(s.get("ip")))
        line("Device", (s.get("user_agent") or "-")[:90], size=8)
        line("Method", "Signature drawn on screen after agreeing to sign electronically")
    c.setFont("Helvetica", 7.5); c.setFillColor(dim)
    foot = (f"Recorded by {info.get('company', '')} ({info.get('registration', '')}). This page is part of the "
            "registered file; any change to the file can be detected on the verification page.")
    words, line_, yy = foot.split(), "", 56
    for w_ in words:
        if stringWidth(line_ + " " + w_, "Helvetica", 7.5) > W - 2 * x0:
            c.drawString(x0, yy, line_.strip()); yy -= 10; line_ = ""
        line_ += " " + w_
    c.drawString(x0, yy, line_.strip())
    c.showPage()
    c.save()
    return buf.getvalue()


def _strip_active_content(writer: PdfWriter):
    """The stamped copy never carries auto-running actions or document
    JavaScript. (The original upload is kept untouched, separately.)"""
    try:
        root = writer._root_object
        for key in ("/OpenAction", "/AA"):
            if key in root:
                del root[key]
        names = root.get("/Names")
        if names is not None:
            names = names.get_object()
            if "/JavaScript" in names:
                del names["/JavaScript"]
    except Exception:
        pass


def embedded_document_id(data: bytes):
    """Read back the Document ID this module wrote into a stamped PDF, if any.
    Used to tell 'this is one of ours but has been changed' from 'unknown file'."""
    try:
        meta = PdfReader(io.BytesIO(data), strict=False).metadata or {}
        value = str(meta.get("/CNCDocumentID") or "")
        return value if re.fullmatch(r"CNC-\d{8}-[A-Z0-9]{6}", value) else None
    except Exception:
        m = re.search(rb"CNC-\d{8}-[A-Z0-9]{6}", data)
        return m.group(0).decode() if m else None


def qr_png(url: str) -> bytes:
    import segno
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=6, border=2)
    return buf.getvalue()
