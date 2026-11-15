"""
Renders a test bill in the layout Indian hospitals commonly use for an in-patient final
bill: letterhead (logo, address, GSTIN, registration), a patient and admission details
box, a numbered table of charges grouped by department with quantity and rate, the
totals with advance and balance, the amount in words, and signatures.

Used by make_samples.py and make_fake_samples.py. render_bill() returns the image and
the boxes of each row's amount and of the totals (make_fake_samples.py pastes over them).
"""

import os
import re
import zlib

from PIL import Image, ImageDraw, ImageFont

W, H = 1240, 1754            # A4 at 150 dpi
M = 64                        # page margin
INK, GREY, LINE, SHADE = (25, 30, 35), (95, 100, 108), (190, 196, 202), (243, 245, 247)

FONTS = {
    False: ["C:/Windows/Fonts/arial.ttf", "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    True: ["C:/Windows/Fonts/arialbd.ttf", "/Library/Fonts/Arial Bold.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
}


def font(size: int, bold: bool = False):
    for path in FONTS[bold]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    raise SystemExit("No TrueType font found (Arial or DejaVu Sans); OCR needs a clear font.")


HOSPITALS = {
    "CITY CARE MULTISPECIALITY HOSPITAL": dict(
        unit="A unit of City Care Health Services Pvt. Ltd.", initials="CC", color=(10, 110, 112),
        address="123 MG Road, Chennai - 600001, Tamil Nadu",
        contact="Ph: 044-2345 6789  |  billing@citycarehospital.in  |  www.citycarehospital.in",
        reg="GSTIN: 33ABCDE1234F1Z5  |  Clinical Est. Reg. No: TN/CHN/2011/0457  |  NABH Accredited",
        prefix="CCH",
    ),
    "SUNRISE GENERAL HOSPITAL": dict(
        unit="Sunrise Healthcare Trust", initials="SG", color=(200, 98, 24),
        address="45 Avinashi Road, Coimbatore - 641018, Tamil Nadu",
        contact="Ph: 0422-245 6789  |  accounts@sunrisegeneral.org  |  www.sunrisegeneral.org",
        reg="GSTIN: 33PQRST5678K1Z2  |  Clinical Est. Reg. No: TN/CBE/2008/0192",
        prefix="SGH",
    ),
    "GREENLEAF MEDICAL CENTRE": dict(
        unit="Greenleaf Clinics LLP", initials="GL", color=(46, 125, 50),
        address="8 Anna Salai, Chennai - 600002, Tamil Nadu",
        contact="Ph: 044-2858 1100  |  care@greenleafmc.in",
        reg="GSTIN: 33ZZZZZ9999Z1Z9  |  Clinical Est. Reg. No: TN/CHN/2019/1123",
        prefix="GMC",
    ),
}

# demo patients (app/seed.py): age, sex, phone, address, payer
PATIENTS = {
    "Ramesh Kumar": (45, "Male", "98401 23456", "14, Gandhi Nagar, Adyar, Chennai", "Suraksha Health Insurance - POL-DEMO01"),
    "Priya Sharma": (32, "Female", "98840 56712", "7B, Lake View Apts, Anna Nagar, Chennai", "Suraksha Health Insurance - POL-DEMO02"),
    "Arjun Reddy": (58, "Male", "94431 88201", "22, Race Course, Coimbatore", "Suraksha Health Insurance - POL-DEMO03"),
    "Meena Iyer": (27, "Female", "90030 41177", "3, Thiru Vi Ka St, Mylapore, Chennai", "Self Pay"),
}

GROUPS = [  # (heading, keywords), first match wins; same order as printed
    ("ROOM & NURSING CHARGES", r"room|ward|bed|nursing|icu"),
    ("PROCEDURES & SURGERY", r"surgery|procedure|operation|delivery|anaesthet|ectomy"),
    ("CONSULTATION & PROFESSIONAL FEES", r"consult|physiotherapy|visit"),
    ("INVESTIGATIONS", r"scan|x-?ray|mri|ct\b|test|blood|ecg|echo|angio|ultrasound|audiometry|diagnostic"),
    ("PHARMACY & CONSUMABLES", r"tablet|tab\b|injection|medicine|capsule|syrup|spray|nebuli|gel|cream|mg\b"),
    ("OTHER CHARGES", r".*"),
]

CONSULTANTS = [
    (r"cardi|valve|echo|angio", "Dr. K. Menon (Cardiology)"),
    (r"spine|fracture|knee|ortho", "Dr. R. Iyer (Orthopaedics)"),
    (r"delivery|gynae", "Dr. L. Nair (Obstetrics & Gynaecology)"),
    (r"\bent\b|audiometry", "Dr. P. Das (ENT)"),
    (r"surgery|appendectomy|hernia", "Dr. A. Prakash (General Surgery)"),
    (r"neuro|brain", "Dr. V. Shankar (Neurology)"),
    (r".*", "Dr. S. Raman (General Medicine)"),
]


def tint(color, strength: float):
    """The colour mixed with white: strength 1 = full colour."""
    return tuple(round(255 - (255 - c) * strength) for c in color)


def money(x: float) -> str:
    """Indian digit grouping: 1,31,360.00"""
    whole, paise = f"{x:.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = ",".join(re.findall(r"\d{1,2}", head[::-1]))[::-1]
        whole = f"{head},{tail}"
    return f"{whole}.{paise}"


_ONES = ("Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen Fifteen "
         "Sixteen Seventeen Eighteen Nineteen").split()
_TENS = "_ _ Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()


def _words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])
    if n < 1000:
        return _ONES[n // 100] + " Hundred" + ("" if n % 100 == 0 else " " + _words(n % 100))
    for size, name in ((10 ** 7, "Crore"), (10 ** 5, "Lakh"), (1000, "Thousand")):
        if n >= size:
            return _words(n // size) + f" {name}" + ("" if n % size == 0 else " " + _words(n % size))
    return ""


def in_words(x: float) -> str:
    rupees, paise = int(x), round((x - int(x)) * 100)
    text = f"Rupees {_words(rupees)}"
    return text + (f" and {_words(paise)} Paise" if paise else "") + " Only"


def _code(text: str, digits: int) -> str:
    return str(zlib.crc32(text.encode()) % 10 ** digits).zfill(digits)


def _days(desc: str) -> int:
    m = re.search(r"\((\d+)\s*days?\)", desc, re.I)
    return int(m.group(1)) if m else 1


def render_bill(spec: dict):
    """spec: hospital, patient, bill_no, admission, discharge, items [(description, amount)],
    optional stated_total (a printed total that differs from the lines)."""
    brand = HOSPITALS[spec["hospital"]]
    color = brand["color"]
    age, sex, phone, address, payer = PATIENTS.get(spec["patient"], (34, "Male", "98765 43210", "Chennai", "Self Pay"))
    items = spec["items"]
    gross = spec.get("stated_total", sum(a for _, a in items))
    advance = 0.0 if payer != "Self Pay" else (2000.0 if gross > 5000 else 0.0)
    outpatient = spec["admission"] == spec["discharge"]
    text_all = " ".join(d for d, _ in items).lower()
    consultant = next(name for pattern, name in CONSULTANTS if re.search(pattern, text_all))

    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f = {k: font(*v) for k, v in dict(name=(30, True), sub=(18,), small=(17,), title=(26, True), label=(19,),
                                       value=(19, True), th=(19, True), td=(20,), group=(17, True), sum=(20,),
                                       sumb=(22, True), foot=(15,)).items()}

    def right(x, y, text, fnt, fill=INK):
        d.text((x - d.textlength(text, font=fnt), y), text, font=fnt, fill=fill)

    # letterhead
    d.rectangle((0, 0, W, 14), fill=tint(color, 0.45))  # light colours drop out in OCR binarisation
    cx, cy, r = M + 48, 108, 48
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=tint(color, 0.32))
    d.rectangle((cx - 9, cy - 30, cx + 9, cy + 30), fill="white")
    d.rectangle((cx - 30, cy - 9, cx + 30, cy + 9), fill="white")
    x = M + 120
    d.text((x, 56), spec["hospital"], font=f["name"], fill=color)  # 30px: OCR misreads larger bold headings
    d.text((x, 96), brand["unit"], font=f["sub"], fill=GREY)
    d.text((x, 122), brand["address"], font=f["sub"], fill=INK)
    d.text((x, 148), brand["contact"], font=f["small"], fill=GREY)
    d.text((x, 172), brand["reg"], font=f["small"], fill=GREY)
    d.rectangle((M, 208, W - M, 211), fill=color)

    title = "OUT-PATIENT BILL" if outpatient else "IN-PATIENT FINAL BILL"
    d.text(((W - d.textlength(title, font=f["title"])) / 2, 228), title, font=f["title"], fill=INK)
    copy_label = "Original - Patient Copy"
    right(W - M, 234, copy_label, f["small"], GREY)

    # patient and admission details
    top, row = 276, 36
    uhid = f"{brand['prefix']}-UH-{_code(spec['patient'], 6)}"
    left_rows = [("Patient Name", spec["patient"]), ("Age / Sex", f"{age} Y / {sex}"), ("UHID", uhid),
                 ("Contact No", phone), ("Address", address), ("Payer", payer)]
    right_rows = [("Bill No", spec["bill_no"]), ("Bill Date", spec["discharge"]),
                  ("IP No" if not outpatient else "OP No", f"{'IP' if not outpatient else 'OP'}/{_code(spec['bill_no'], 5)}"),
                  *([("Visit Date", f"{spec['admission']} 10:15"), ("Department", consultant.split("(")[-1].rstrip(")"))]
                    if outpatient else [("Admission Date", f"{spec['admission']} 10:15"),
                                        ("Discharge Date", f"{spec['discharge']} 11:40")]),
                  ("Consultant", consultant)]
    d.rectangle((M, top, W - M, top + row * 6 + 16), fill=SHADE, outline=LINE)
    for i, ((l1, v1), (l2, v2)) in enumerate(zip(left_rows, right_rows)):
        y = top + 10 + i * row
        d.text((M + 16, y), l1, font=f["label"], fill=GREY)
        d.text((M + 180, y), f": {v1}", font=f["value"], fill=INK)
        d.text((660, y), l2, font=f["label"], fill=GREY)
        d.text((830, y), f": {v2}", font=f["value"], fill=INK)

    # charges table
    cols = dict(sno=M + 14, part=M + 80, qty=820, rate=1000, amt=W - M - 14)
    y = top + row * 6 + 40
    d.rectangle((M, y, W - M, y + 40), fill=tint(color, 0.15))
    d.line((M, y + 40, W - M, y + 40), fill=color, width=2)
    d.text((cols["sno"], y + 9), "S.No", font=f["th"], fill=INK)
    d.text((cols["part"], y + 9), "Particulars", font=f["th"], fill=INK)
    right(cols["qty"], y + 9, "Qty", f["th"])
    right(cols["rate"], y + 9, "Rate (Rs.)", f["th"])
    right(cols["amt"], y + 9, "Amount (Rs.)", f["th"])
    y += 48

    grouped = {}
    for index, (desc, amount) in enumerate(items):
        heading = next(h for h, pattern in GROUPS if re.search(pattern, desc.lower()))
        grouped.setdefault(heading, []).append((index, desc, amount))
    boxes, sno = {}, 0
    for heading, _ in GROUPS:
        if heading not in grouped:
            continue
        d.text((cols["part"], y + 4), heading, font=f["group"], fill=color)
        y += 32
        for index, desc, amount in grouped[heading]:
            sno += 1
            days = _days(desc)
            qty = days if days > 1 and round(amount * 100) % days == 0 else 1  # else billed as one package
            d.text((cols["sno"] + 8, y + 6), str(sno), font=f["td"], fill=INK)
            d.text((cols["part"], y + 6), desc, font=f["td"], fill=INK)
            right(cols["qty"], y + 6, str(qty), f["td"])
            right(cols["rate"], y + 6, money(amount / qty), f["td"])
            right(cols["amt"], y + 6, money(amount), f["td"])
            boxes[index] = (cols["qty"] - 60, y + 2, W - M - 4, y + 34)
            y += 38
            d.line((M, y - 2, W - M, y - 2), fill=LINE)
    d.line((M, y + 4, W - M, y + 4), fill=INK, width=2)

    # totals
    y += 20
    net = gross
    summary = [("Gross Total", money(gross), False), ("Less: Discount", money(0), False), ("Net Amount", money(net), False),
               ("Less: Advance Paid", money(advance), False), ("Balance Payable", money(net - advance), True)]
    sum_top = y
    for label, value, bold in summary:
        fnt = f["sumb"] if bold else f["sum"]
        d.text((cols["qty"] - 40, y), label, font=fnt, fill=INK)
        right(cols["amt"], y, value, fnt)
        y += 34
    boxes["summary"] = (cols["qty"] - 50, sum_top - 6, W - M - 4, y)
    y += 12
    words = f"Amount in words: {in_words(net)}"
    d.text((M, y), words, font=f["label"], fill=INK)
    boxes["words"] = (M, y - 4, W - M - 4, y + 28)
    y += 34
    mode = "Cashless (TPA)" if payer != "Self Pay" else "Cash / UPI"
    d.text((M, y), f"Payment mode: {mode}", font=f["label"], fill=GREY)

    # signatures and footer
    y = H - 230
    d.text((M, y), "Prepared by: Billing Desk", font=f["label"], fill=INK)
    d.line((W - M - 300, y + 40, W - M, y + 40), fill=INK)
    right(W - M, y + 48, "Authorised Signatory", f["label"])
    right(W - M, y + 74, f"for {spec['hospital'].title()}", f["small"], GREY)
    d.line((M, H - 110, W - M, H - 110), fill=LINE)
    notes = ["This is a computer generated bill. Please retain it for insurance and tax purposes.",
             "Charges are as per the hospital tariff. Billing queries: contact the billing desk within 7 days."]
    for i, note in enumerate(notes):
        d.text((M, H - 98 + i * 22), note, font=f["foot"], fill=GREY)
    right(W - M, H - 98, "Page 1 of 1", f["foot"], GREY)
    d.rectangle((0, H - 14, W, H), fill=tint(color, 0.45))
    return img, boxes
