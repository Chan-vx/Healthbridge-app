"""
Generates fake bills for testing the authenticity checks (saved in fake_bills/).
Every price on them is fair, so Member 3's price checks pass; only the
authenticity checks can catch them.

    python make_fake_samples.py
"""

import io
import os
from datetime import datetime

from PIL import Image

from bill_template import font, render_bill
from make_samples import CC, SG, draw_bill

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_bills")

FAKES = {
    # printed by a hospital that is not the one chosen on upload
    "fake_01_wrong_hospital.png": dict(
        hospital="GREENLEAF MEDICAL CENTRE", address="8 Anna Salai, Chennai - 600002 | GSTIN: 33ZZZZZ9999Z1Z9",
        patient="Priya Sharma", bill_no="GMC-2026-00417", admission="21-Oct-2026", discharge="23-Oct-2026",
        items=[("Room Rent (2 days)", 10300), ("Consultation - Specialist", 1000), ("Ultrasound Abdomen Scan", 3300),
               ("Medicines - Antacid syrup", 260)],
    ),
    # someone else's bill
    "fake_02_wrong_patient.png": dict(
        hospital=CC[0], address=CC[1], patient="Rahul Verma", bill_no="CCH-2026-02231",
        admission="24-Oct-2026", discharge="26-Oct-2026",
        items=[("Room Rent (2 days)", 10100), ("Consultation - Physician", 1000), ("Blood Test - Lipid Profile", 3300),
               ("Nursing Charges (2 days)", 4000)],
    ),
    # bill number of the demo bill CCH-2026-00891 (Ramesh's appendix bill in the seed data)
    "fake_03_reused_bill_number.png": dict(
        hospital=CC[0], address=CC[1], patient="Ramesh Kumar", bill_no="CCH-2026-00891",
        admission="27-Oct-2026", discharge="29-Oct-2026",
        items=[("Room Rent (2 days)", 10200), ("Consultation - Neurologist", 1000), ("MRI Scan Brain", 3400),
               ("Nursing Charges (2 days)", 4100)],
    ),
    # discharged before being admitted
    "fake_04_impossible_dates.png": dict(
        hospital=SG[0], address=SG[1], patient="Arjun Reddy", bill_no="SGH-2026-02260",
        admission="30-Oct-2026", discharge="26-Oct-2026",
        items=[("Room Rent (3 days)", 9200), ("Consultation - Physician", 600), ("X-Ray Chest", 2000),
               ("Nursing Charges (3 days)", 3500)],
    ),
}


# A genuine bill as the patient received it. The demo data (app/seed.py) holds City Care's own
# record of it, so uploading it as Priya shows "Matches hospital record".
GENUINE_COPY = dict(
    hospital=CC[0], address=CC[1], patient="Priya Sharma", bill_no="CCH-2026-02350",
    admission="06-Nov-2026", discharge="08-Nov-2026",
    items=[("Room Rent (2 days)", 10250), ("Consultation - Physician", 1000), ("Blood Test - Vitamin D", 3300),
           ("Medicines - Vitamin D3 capsules", 270)],
)
COPIES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patient_copies")


def jpeg(img: Image.Image, quality: int, **kwargs) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, **kwargs)
    return buf.getvalue()


def photoshop_bill(path: str):
    """A genuine-looking bill whose photo metadata says it went through Photoshop."""
    img = draw_bill(dict(
        hospital=CC[0], address=CC[1], patient="Priya Sharma", bill_no="CCH-2026-02275",
        admission="01-Nov-2026", discharge="03-Nov-2026",
        items=[("Room Rent (2 days)", 10400), ("Consultation - Gynaecologist", 1000), ("Blood Test - Thyroid", 3300),
               ("Medicines - Iron tablets", 270)],
    ))
    exif = Image.Exif()
    exif[305] = "Adobe Photoshop 25.0 (Windows)"
    with open(path, "wb") as f:
        f.write(jpeg(img, 88, exif=exif))


def pasted_amount_bill(path: str):
    """A photographed bill (JPEG) where one amount was replaced by pasting new text over it.
    No metadata gives it away; error level analysis does."""
    spec = dict(
        hospital=SG[0], address=SG[1], patient="Arjun Reddy", bill_no="SGH-2026-02291",
        admission="04-Nov-2026", discharge="07-Nov-2026",
        items=[("Room Rent (3 days)", 9300), ("Surgery - Hernia Repair", 36000), ("Consultation - Surgeon", 600),
               ("Nursing Charges (3 days)", 3600), ("Tablet Paracetamol 500mg", 150)],
    )
    photo = Image.open(io.BytesIO(jpeg(draw_bill(spec), 70))).convert("RGB")  # the original photo
    # the forger renders a higher surgery amount and pastes it over the original row, and
    # over the totals and amount in words so the bill still adds up
    spec["items"][1] = ("Surgery - Hernia Repair", 86000)
    forged, boxes = render_bill(spec)
    for box in (boxes[1], boxes["summary"], boxes["words"]):
        photo.paste(forged.crop(box), box[:2])
    with open(path, "wb") as f:
        f.write(jpeg(photo, 92))


def edited_pdf(path: str):
    """A PDF bill re-saved by an online PDF editor after it was made."""
    img = draw_bill(dict(
        hospital=SG[0], address=SG[1], patient="Ramesh Kumar", bill_no="SGH-2026-02304",
        admission="08-Nov-2026", discharge="10-Nov-2026",
        items=[("Room Rent (2 days)", 6300), ("Consultation - Physician", 620), ("Blood Test - Dengue NS1", 1900),
               ("Nursing Charges (2 days)", 2400), ("Tablet Paracetamol 500mg", 150)],
    ))
    img.save(path, "PDF", resolution=150, creator="iLovePDF", producer="iLovePDF",
             creationDate=datetime(2026, 11, 10, 9, 0).timetuple(), modDate=datetime(2026, 11, 12, 18, 30).timetuple())


if __name__ == "__main__":
    font(16)  # fail early if no font is available
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, spec in FAKES.items():
        draw_bill(spec).save(os.path.join(OUT_DIR, name))
        print("saved fake_bills/" + name)
    photoshop_bill(os.path.join(OUT_DIR, "fake_05_photoshop_metadata.jpg"))
    pasted_amount_bill(os.path.join(OUT_DIR, "fake_06_pasted_amount.jpg"))
    edited_pdf(os.path.join(OUT_DIR, "fake_07_edited_pdf.pdf"))
    print("saved fake_bills/fake_05_photoshop_metadata.jpg, fake_06_pasted_amount.jpg, fake_07_edited_pdf.pdf")
    os.makedirs(COPIES_DIR, exist_ok=True)
    draw_bill(GENUINE_COPY).save(os.path.join(COPIES_DIR, "copy_01_genuine_priya_citycare.png"))
    print("saved patient_copies/copy_01_genuine_priya_citycare.png")
