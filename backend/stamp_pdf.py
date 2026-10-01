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
    c.setFillColor(color)
    c.setStrokeColor(color)
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


def _safe_color(value: str):
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value or ""):
        value = "#16168a"
    return HexColor(value)


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
        if it["kind"] == "image":
            c.drawImage(images[it["image"]], -pw / 2, -ph / 2, pw, ph, mask="auto")
        else:
            _draw_text(c, it["text"], _safe_color(it.get("color")), pw, ph, bool(it.get("border", True)))
        c.restoreState()
    c.showPage()
    c.save()
    return PdfReader(io.BytesIO(buf.getvalue())).pages[0]


def render(original: bytes, placements: list, images: dict, *, document_id: str,
           footer_text: str = None, qr_png: bytes = None, qr_position: str = "bottom-right",
           company: str = "") -> bytes:
    """Build the final stamped PDF.

    placements: [{kind:'image'|'text', page (1-based), x, y, w, h (fractions of the
                 displayed page), rotation, opacity, image (key into `images`) | text, color, border}]
    images:     {key: PNG bytes}

    Everything visible (stamps, footer, QR) is added here, before the caller
    hashes the result - nothing may touch the bytes afterwards."""
    reader = open_pdf(original)
    writer = PdfWriter(clone_from=reader)
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
