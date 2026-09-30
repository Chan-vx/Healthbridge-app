"""
Generates the test bill images/PDF in this folder, in the same layout as
Member 3's sample_bill_1.png so the OCR parser can read them.

    python make_samples.py
"""

import os

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
]


def font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


BILLS = {
    "bill_01_clean_sunrise.png": dict(
        hospital="SUNRISE GENERAL HOSPITAL",
        address="45 Avinashi Road, Coimbatore - 641018 | GSTIN: 33PQRST5678K1Z2",
        patient="Arjun Reddy", bill_no="SGH-2026-01142",
        admission="02-Sep-2026", discharge="04-Sep-2026",
        items=[
            ("Room Rent (2 days)", 6200), ("Consultation - Physician", 620),
            ("Blood Test - CBC", 2050), ("X-Ray Chest", 2100),
            ("Tablet Amoxicillin 500mg", 150), ("Nursing Charges (2 days)", 2350),
        ],
    ),
    "bill_02_overcharged_citycare.png": dict(
        hospital="CITY CARE MULTISPECIALITY HOSPITAL",
        address="123 MG Road, Chennai - 600001 | GSTIN: 33ABCDE1234F1Z5",
        patient="Priya Sharma", bill_no="CCH-2026-01377",
        admission="11-Sep-2026", discharge="14-Sep-2026",
        items=[
            ("Room Rent (3 days)", 45000), ("Surgery - Hernia Repair", 61000),
            ("MRI Scan Abdomen", 18000), ("Nursing Charges (3 days)", 6100),
            ("Consultation - Specialist", 1000), ("Injection Pantoprazole 40mg", 260),
        ],
    ),
    "bill_03_duplicates_sunrise.png": dict(
        hospital="SUNRISE GENERAL HOSPITAL",
        address="45 Avinashi Road, Coimbatore - 641018 | GSTIN: 33PQRST5678K1Z2",
        patient="Ramesh Kumar", bill_no="SGH-2026-01188",
        admission="15-Sep-2026", discharge="16-Sep-2026",
        items=[
            ("Room Rent (1 day)", 3100), ("Consultation - Physician", 600),
            ("Injection Ceftriaxone", 160), ("Injection Ceftriaxone", 160),
            ("Blood Test - CBC", 2000), ("Blood Test CBC", 2000),
            ("Nursing Charges (1 day)", 1200),
        ],
    ),
    "bill_04_total_mismatch_citycare.png": dict(
        hospital="CITY CARE MULTISPECIALITY HOSPITAL",
        address="123 MG Road, Chennai - 600001 | GSTIN: 33ABCDE1234F1Z5",
        patient="Meena Iyer", bill_no="CCH-2026-01402",
        admission="18-Sep-2026", discharge="18-Sep-2026",
        items=[
            ("Consultation - Dermatologist", 1000), ("Blood Test - Thyroid Profile", 3300),
            ("Tablet Levocetirizine 5mg", 250),
        ],
        stated_total=6550,  # printed total is Rs.2,000 more than the items add up to
    ),
    "bill_05_inflated_cardiac_citycare.png": dict(
        hospital="CITY CARE MULTISPECIALITY HOSPITAL",
        address="123 MG Road, Chennai - 600001 | GSTIN: 33ABCDE1234F1Z5",
        patient="Arjun Reddy", bill_no="CCH-2026-01455",
        admission="20-Sep-2026", discharge="30-Sep-2026",
        items=[
            ("Room Rent (10 days)", 90000), ("Surgery - Valve Replacement", 620000),
            ("Anaesthetist Fee", 70000), ("ICU Nursing Charges (10 days)", 65000),
            ("Diagnostic - Echo Cardiogram Scan", 28000), ("Medicines - Warfarin tablets", 6400),
        ],
    ),
}


# Second set: new treatments for testing the patient-upload flow (saved in new_bills/)
CC = ("CITY CARE MULTISPECIALITY HOSPITAL", "123 MG Road, Chennai - 600001 | GSTIN: 33ABCDE1234F1Z5")
SG = ("SUNRISE GENERAL HOSPITAL", "45 Avinashi Road, Coimbatore - 641018 | GSTIN: 33PQRST5678K1Z2")
NEW_BILLS = {
    "new_bill_01_maternity_citycare.png": dict(
        hospital=CC[0], address=CC[1], patient="Priya Sharma", bill_no="CCH-2026-02011",
        admission="03-Oct-2026", discharge="05-Oct-2026",
        items=[
            ("Room Rent (2 days)", 10200), ("Procedure - Normal Delivery", 58000),
            ("Consultation - Gynaecologist", 1000), ("Nursing Charges (2 days)", 4000),
            ("Blood Test - Hemoglobin", 3300), ("Medicines - Iron tablets", 260),
        ],
    ),
    "new_bill_02_dengue_sunrise.png": dict(
        hospital=SG[0], address=SG[1], patient="Ramesh Kumar", bill_no="SGH-2026-02054",
        admission="06-Oct-2026", discharge="10-Oct-2026",
        items=[
            ("Room Rent (4 days)", 12400), ("Consultation - Physician", 600),
            ("Blood Test - Platelet Count", 2000), ("Blood Test Platelet Count", 2000),
            ("Injection Paracetamol IV", 160), ("Ultrasound Abdomen Scan", 7500),
            ("Nursing Charges (4 days)", 4700),
        ],
    ),
    "new_bill_03_fracture_sunrise.png": dict(
        hospital=SG[0], address=SG[1], patient="Arjun Reddy", bill_no="SGH-2026-02077",
        admission="08-Oct-2026", discharge="11-Oct-2026",
        items=[
            ("Surgery - Fracture Fixation", 36000), ("X-Ray Leg", 2000),
            ("Room Rent (3 days)", 9100), ("Nursing Charges (3 days)", 3500),
            ("Tablet Aceclofenac 100mg", 150), ("Physiotherapy consultation", 600),
            ("Cosmetic hair spa (non-medical)", 1800),
        ],
    ),
    "new_bill_04_ent_no_insurance_citycare.png": dict(
        hospital=CC[0], address=CC[1], patient="Meena Iyer", bill_no="CCH-2026-02093",
        admission="12-Oct-2026", discharge="12-Oct-2026",
        items=[
            ("Consultation - ENT Specialist", 1000), ("Diagnostic - Audiometry test", 3400),
            ("Medicines - Nasal spray", 270),
        ],
    ),
    "new_bill_05_appendix_citycare.png": dict(
        hospital=CC[0], address=CC[1], patient="Priya Sharma", bill_no="CCH-2026-02118",
        admission="14-Oct-2026", discharge="18-Oct-2026",
        items=[
            ("Room Rent (4 days)", 38000), ("Surgery - Appendectomy", 62000),
            ("Anaesthetist Fee", 12000), ("CT Scan Abdomen", 3400),
            ("Nursing Charges (4 days)", 8000), ("Medicines - Antibiotic course", 270),
        ],
    ),
    "new_bill_06_spine_inflated_citycare.png": dict(
        hospital=CC[0], address=CC[1], patient="Arjun Reddy", bill_no="CCH-2026-02140",
        admission="15-Oct-2026", discharge="22-Oct-2026",
        items=[
            ("Room Rent (7 days)", 70000), ("Surgery - Spine Fusion", 560000),
            ("Anaesthetist Fee", 65000), ("ICU Nursing Charges (7 days)", 49000),
            ("MRI Scan Spine", 26000), ("Medicines - Pain management", 6000),
        ],
    ),
}


def draw_bill(spec) -> Image.Image:
    width, height = 900, 1200
    img = Image.new("RGB", (width, height), color="white")
    d = ImageDraw.Draw(img)
    title, header, body = font(28), font(18), font(16)

    y = 40
    d.text((40, y), spec["hospital"], font=title, fill="black"); y += 40
    d.text((40, y), spec["address"], font=body, fill="black"); y += 40
    d.line((40, y, 860, y), fill="black", width=2); y += 20
    d.text((40, y), f"Patient: {spec['patient']}        Bill No: {spec['bill_no']}", font=header, fill="black"); y += 30
    d.text((40, y), f"Admission Date: {spec['admission']}   Discharge Date: {spec['discharge']}", font=header, fill="black"); y += 40
    d.line((40, y, 860, y), fill="black", width=1); y += 20
    d.text((40, y), "ITEMIZED CHARGES", font=header, fill="black"); y += 35
    d.text((40, y), "Description", font=body, fill="black")
    d.text((650, y), "Amount (Rs.)", font=body, fill="black"); y += 25
    d.line((40, y, 860, y), fill="gray", width=1); y += 15

    total = 0.0
    for desc, amt in spec["items"]:
        d.text((40, y), desc, font=body, fill="black")
        d.text((650, y), f"{amt:.2f}", font=body, fill="black")
        total += amt
        y += 28
    y += 10
    d.line((40, y, 860, y), fill="black", width=2); y += 20
    printed = spec.get("stated_total", total)
    d.text((40, y), f"TOTAL AMOUNT DUE: Rs. {printed:.2f}", font=header, fill="black")
    return img


if __name__ == "__main__":
    for name, spec in BILLS.items():
        img = draw_bill(spec)
        img.save(os.path.join(OUT_DIR, name))
        print("saved", name)
    # the clean bill again as a PDF, to test the PDF path of the OCR
    draw_bill(BILLS["bill_01_clean_sunrise.png"]).save(os.path.join(OUT_DIR, "bill_06_clean_sunrise.pdf"), "PDF", resolution=100)
    print("saved bill_06_clean_sunrise.pdf")
    new_dir = os.path.join(OUT_DIR, "new_bills")
    os.makedirs(new_dir, exist_ok=True)
    for name, spec in NEW_BILLS.items():
        draw_bill(spec).save(os.path.join(new_dir, name))
        print("saved new_bills/" + name)
    # the appendix bill also as a PDF
    draw_bill(NEW_BILLS["new_bill_05_appendix_citycare.png"]).save(
        os.path.join(new_dir, "new_bill_07_appendix_citycare.pdf"), "PDF", resolution=100)
    print("saved new_bills/new_bill_07_appendix_citycare.pdf")
