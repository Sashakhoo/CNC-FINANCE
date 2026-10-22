"""Edit tools (text, shapes, drawing, links, form fields, images) and
sending a document for other people to sign."""
import base64
import io

import fitz  # PyMuPDF - only used by tests, to look at the rendered result
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from reportlab.pdfgen import canvas

import main
import stamp_pdf
from test_stamp import ORIGIN, app_client, boss, staff, staff2, reader, upload, make_pdf, chop_id, _sig_png  # noqa: F401


def form_pdf():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    c.drawString(72, 780, "Application form")
    c.acroForm.textfield(name="full_name", x=72, y=700, width=300, height=22, value="")
    c.acroForm.checkbox(name="agree", x=72, y=650, size=16, checked=False)
    c.save()
    return buf.getvalue()


def box(**kw):
    return {"page": 1, "pages": "current", "x": 0.1, "y": 0.1, "w": 0.3, "h": 0.05,
            "rotation": 0, "opacity": 1, **kw}


def finalize(c, did, items, fields=None):
    return c.post(f"/api/stamp/documents/{did}/finalize", json={"items": items, "fields": fields or {}},
                  headers=ORIGIN)


def test_text_shapes_drawing_and_links(staff):
    did = upload(staff).json()["document_id"]
    items = [
        box(kind="plain", text="Name: ALEX\nDesignation: DIRECTOR", fs=0.016, font="helv", bold=True),
        box(kind="plain", text="Times text", fs=0.02, font="times", italic=True, y=0.3),
        box(kind="shape", shape="whiteout", y=0.4), box(kind="shape", shape="highlight", y=0.45, opacity=0.45),
        box(kind="shape", shape="rect", stroke="#c0261b", sw=0.002, y=0.5),
        box(kind="shape", shape="ellipse", fill="#d7f26d", y=0.55),
        box(kind="shape", shape="arrow", y=0.6, h=0.01), box(kind="shape", shape="line", y=0.62, h=0.004),
        box(kind="shape", shape="check", w=0.03, h=0.02, y=0.65), box(kind="shape", shape="cross", w=0.03, h=0.02, y=0.68),
        box(kind="shape", shape="dot", w=0.02, h=0.015, y=0.7),
        box(kind="ink", points=[[0, 0], [0.5, 1], [1, 0.2]], stroke="#16168a", y=0.75),
        box(kind="link", url="https://codencode.my", y=0.85),
    ]
    r = finalize(staff, did, items)
    assert r.status_code == 200, r.text
    final = staff.get(f"/api/stamp/documents/{did}/download").content
    page = fitz.open(stream=final, filetype="pdf")[0]
    text = page.get_text()
    assert "Name: ALEX" in text and "Designation: DIRECTOR" in text and "Times text" in text
    # a highlight is see-through: on white paper it comes out pale, not solid yellow
    pix = page.get_pixmap(dpi=36)
    px = pix.pixel(int(pix.width * 0.25), int(pix.height * 0.475))
    assert px[2] > 150, px
    links = page.get_links()
    assert [ln["uri"] for ln in links] == ["https://codencode.my"]
    # the free text sits where the editor put it: top-left of its box
    hit = page.search_for("Name: ALEX")[0]
    assert abs(hit.x0 / page.rect.width - 0.1) < 0.01 and abs(hit.y0 / page.rect.height - 0.1) < 0.02


def test_bad_inputs_are_rejected(staff):
    did = upload(staff).json()["document_id"]
    assert finalize(staff, did, [box(kind="link", url="javascript:alert(1)")]).status_code == 400
    assert finalize(staff, did, [box(kind="shape", shape="star")]).status_code == 400
    assert finalize(staff, did, [box(kind="plain", text="你好")]).status_code == 400
    assert finalize(staff, did, [box(kind="ink", points=[[0, 0]])]).status_code == 400
    assert finalize(staff, did, [box(kind="image", image_id=999)]).status_code == 400
    assert finalize(staff, did, [box(kind="signer", signer_name="Ali", field="signature")]).status_code == 400


def test_form_fields_are_filled_and_flattened(staff):
    original = form_pdf()
    up = upload(staff, original).json()
    detail = staff.get(f"/api/stamp/documents/{up['document_id']}").json()
    names = {f["name"]: f for f in detail["fields"]}
    assert names["full_name"]["type"] == "text" and names["agree"]["type"] == "checkbox"
    f = names["full_name"]                                   # geometry is in display fractions
    assert abs(f["x"] - 72 / 595) < 0.005 and abs(f["y"] - (842 - 722) / 842) < 0.005
    r = finalize(staff, up["document_id"], [], fields={"full_name": "Alex Appleseed", "agree": "Yes",
                                                       "not_a_field": "ignored"})
    assert r.status_code == 200, r.text
    final = staff.get(f"/api/stamp/documents/{up['document_id']}/download").content
    rd = PdfReader(io.BytesIO(final))
    assert "/AcroForm" not in rd.trailer["/Root"]                # flattened - nothing left to re-type
    assert "/Annots" not in rd.pages[0]
    assert "Alex Appleseed" in rd.pages[0].extract_text()


def test_document_images(staff, staff2):
    did = upload(staff).json()["document_id"]
    iid = staff.post(f"/api/stamp/documents/{did}/images", content=_sig_png(), headers=ORIGIN).json()["id"]
    assert staff.get(f"/api/stamp/documents/{did}/images/{iid}").status_code == 200
    assert staff2.get(f"/api/stamp/documents/{did}/images/{iid}").status_code == 403
    other = upload(staff).json()["document_id"]               # an image belongs to its own document only
    assert finalize(staff, other, [box(kind="image", image_id=iid)]).status_code == 400
    assert finalize(staff, did, [box(kind="image", image_id=iid)]).status_code == 200


def data_url():
    return "data:image/png;base64," + base64.b64encode(_sig_png()).decode()


def test_send_for_signature_end_to_end(staff, staff2):
    did = upload(staff, make_pdf(2)).json()["document_id"]
    items = [{**box(kind="stamp", stamp_id=chop_id(staff), x=0.6, y=0.7, w=0.2, h=0.14)},
             box(kind="signer", signer_name="Khor Witness", signer_contact="witness@example.com",
                 field="signature", x=0.1, y=0.7, w=0.25, h=0.06),
             box(kind="signer", signer_name="Khor Witness", field="text", x=0.1, y=0.78, w=0.3, h=0.025),
             box(kind="signer", signer_name="Khor Witness", field="date", x=0.1, y=0.81, w=0.2, h=0.025),
             box(kind="signer", signer_name="Second Party", field="initials", pages="all", x=0.85, y=0.92,
                 w=0.08, h=0.04)]
    # an ordinary export is refused while there are boxes for others
    assert finalize(staff, did, items).status_code == 400
    r = staff.post(f"/api/stamp/documents/{did}/send-for-signature", json={"items": items}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    links = {ln["name"]: ln["url"] for ln in r.json()["links"]}
    assert set(links) == {"Khor Witness", "Second Party"}
    doc = staff.get(f"/api/stamp/documents/{did}").json()
    assert doc["can_edit"] is False and doc["signing"]["total"] == 2
    assert staff.put(f"/api/stamp/documents/{did}/draft", json={"items": []}, headers=ORIGIN).status_code == 409
    assert staff2.get(f"/api/stamp/documents/{did}/signing").status_code == 403

    anon = TestClient(main.app)
    t1 = links["Khor Witness"].rsplit("/", 1)[1]
    t2 = links["Second Party"].rsplit("/", 1)[1]
    info = anon.get(f"/api/sign/{t1}").json()
    assert info["status"] == "PENDING" and {f["field"] for f in info["fields"]} == {"signature", "text", "date"}
    assert anon.get(f"/api/sign/{t1}/file").content[:5] == b"%PDF-"
    assert anon.get("/api/sign/not-a-real-token").status_code == 404
    assert anon.post(f"/api/sign/{t1}", json={"consent": False}).status_code == 422
    text_idx = next(f["idx"] for f in info["fields"] if f["field"] == "text")
    assert anon.post(f"/api/sign/{t1}", json={"consent": True, "signature": data_url()}).status_code == 422
    ok = anon.post(f"/api/sign/{t1}", json={"consent": True, "signature": data_url(),
                                            "texts": {str(text_idx): "Lead of Sales"}}).json()
    assert ok["status"] == "SIGNED" and ok["completed"] is False
    assert anon.post(f"/api/sign/{t1}", json={"consent": True, "signature": data_url()}).status_code == 409

    # a renewed link replaces the old one
    rid = next(q["id"] for q in staff.get(f"/api/stamp/documents/{did}/signing").json()["requests"]
               if q["name"] == "Second Party")
    new = staff.post(f"/api/stamp/documents/{did}/signing/{rid}/link", headers=ORIGIN).json()["url"]
    assert anon.get(f"/api/sign/{t2}").status_code == 404
    t2 = new.rsplit("/", 1)[1]
    done = anon.post(f"/api/sign/{t2}", json={"consent": True, "initials": data_url()}).json()
    assert done["completed"] is True

    d = staff.get(f"/api/stamp/documents/{did}").json()
    assert d["status"] == "COMPLETED" and d["page_count"] == 2
    final = staff.get(f"/api/stamp/documents/{did}/download").content
    assert stamp_pdf.sha256_hex(final) == d["final_sha256"]
    pdf = fitz.open(stream=final, filetype="pdf")
    assert len(pdf) == 3                                          # + signature certificate
    cert = pdf[2].get_text()
    assert "Signature Certificate" in cert and "Khor Witness" in cert and "Second Party" in cert
    assert "Lead of Sales" in pdf[0].get_text()
    assert len(pdf[1].get_images()) >= 1                         # initials repeated on page 2
    assert anon.post("/api/verify", content=final).json()["status"] == "VERIFIED"
    assert anon.get(f"/api/sign/{t1}/file?download=1").headers["content-disposition"].startswith("attachment")


def test_decline_and_cancel(staff):
    did = upload(staff).json()["document_id"]
    items = [box(kind="signer", signer_name="Client", field="signature")]
    links = staff.post(f"/api/stamp/documents/{did}/send-for-signature", json={"items": items},
                       headers=ORIGIN).json()["links"]
    token = links[0]["url"].rsplit("/", 1)[1]
    anon = TestClient(main.app)
    assert anon.post(f"/api/sign/{token}/decline", json={"reason": "Wrong amount"}).json()["status"] == "DECLINED"
    assert staff.get(f"/api/stamp/documents/{did}").json()["signing"]["declined"] == 1
    assert staff.post(f"/api/stamp/documents/{did}/signing/cancel", headers=ORIGIN).status_code == 200
    assert staff.get(f"/api/stamp/documents/{did}").json()["can_edit"] is True
    assert anon.get(f"/api/sign/{token}").json()["status"] == "CANCELLED"
