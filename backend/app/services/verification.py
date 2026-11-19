"""
Bill authenticity checks: is this a real bill from this hospital for this patient?

The ML modules judge prices (Member 3) and claim risk (Member 2); neither can tell
a genuine bill from a fake one with believable prices. These checks cover that:

  * hospital's record    - a bill a patient uploads is looked up by its OCR-read bill
                           number among the bills the hospital itself submitted, and
                           compared date by date and line by line (reconcile)
  * record cross-checks  - printed hospital and patient names match the accounts,
                           the bill number and the bill itself were not used before,
                           the dates are possible and inside the policy period
  * tampering signs      - editing software in the file's metadata, and PDFs modified
                           or saved again after creation
  * error level analysis - a picture of JPEG photos that shows pasted areas, for the
                           reviewer to look at (not scored; see error_level_image)

Each check returns pass / warn / fail with a plain-language detail. Tampering signs
are only warnings: metadata can be stripped or rewritten. The strongest control is separate: a bill a patient uploads must be
confirmed by the hospital before it can be claimed (see routers/bills.py).
"""

import hashlib
import io
import re
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageChops, ImageOps
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Bill, Hospital, Policy, User

DATE_FORMATS = ("%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %b %Y")

# Programs that edit documents or photos. A genuine hospital bill is printed by the
# hospital's billing system and scanned or photographed; it is not saved by these.
EDITORS = ("Photoshop", "GIMP", "Paint.NET", "Canva", "Pixlr", "Snapseed", "Lightroom", "Affinity", "PicsArt",
           "Photopea", "Fotor", "Inkscape", "Illustrator", "PDFescape", "Sejda", "Smallpdf", "iLovePDF",
           "PDF-XChange Editor", "Foxit PhantomPDF", "Foxit PDF Editor", "Nitro Pro", "PDFelement",
           "PDF Candy", "Microsoft Word", "LibreOffice")

# Error level analysis: re-save quality for the picture shown to reviewers
ELA_QUALITY = 70

# Checks that mean "this bill was already submitted": a claim on it is refused.
DUPLICATE_CHECKS = ("duplicate_file", "duplicate_bill_number", "duplicate_content")

# Hospital confirmation (Bill.verification_status)
CONFIRMED = ("hospital_uploaded", "confirmed")
# a patient's copy of a bill the hospital already submitted: never claimed or counted twice
COPIES = ("matched", "mismatch")


# ---------------------------------------------------------------- helpers


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _norm(text: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _token_match(a: str, b: str) -> bool:
    if len(a) == 1 or len(b) == 1:  # an initial ("R. Kumar") matches the full name
        return a[0] == b[0]
    return SequenceMatcher(None, a, b).ratio() >= 0.8


def _covered(tokens: list[str], other: list[str]) -> float:
    return sum(any(_token_match(t, o) for o in other) for t in tokens) / len(tokens) if tokens else 0.0


def name_similarity(printed: Optional[str], record: Optional[str]) -> float:
    """0-1 similarity of two names, tolerant of case, punctuation, word order and initials."""
    p, r = _norm(printed), _norm(record)
    if not p or not r:
        return 0.0
    pt, rt = p.split(), r.split()
    tokens = (_covered(pt, rt) + _covered(rt, pt)) / 2
    return round(max(SequenceMatcher(None, p, r).ratio(), tokens), 3)


def parse_date(text: Optional[str]) -> Optional[date]:
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def content_fingerprint(items: list[dict], hospital_key: str, admission: Optional[str],
                        discharge: Optional[str]) -> str:
    """Same hospital, same dates and the same lines and amounts = the same bill, however it was entered."""
    lines = sorted(f"{_norm(i['description'])}|{float(i['amount']):.2f}" for i in items)
    return sha256("\n".join([hospital_key, _norm(admission), _norm(discharge), *lines]).encode())


def _check(key: str, name: str, status: str, detail: str) -> dict:
    return {"key": key, "name": name, "status": status, "detail": detail}


def overall(checks: list[dict]) -> str:
    statuses = {c["status"] for c in checks}
    return "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"  # "waiting" is neutral


# ---------------------------------------------------------------- tampering


def _editor_in(text: str) -> Optional[str]:
    lower = text.lower()
    return next((e for e in EDITORS if e.lower() in lower), None)


def _image_signals(path: Path, raw: bytes) -> list[str]:
    signals = []
    with Image.open(path) as img:
        exif = img.getexif()
        software = " ".join(str(v) for v in (exif.get(305), img.info.get("Software"), img.info.get("software")) if v)
        xmp = img.info.get("xmp") or img.info.get("XML:com.adobe.xmp") or b""
        if isinstance(xmp, bytes):
            xmp = xmp.decode("utf-8", "ignore")
        editor = _editor_in(f"{software} {xmp}") or _editor_in(raw[:65536].decode("latin-1"))
        if editor:
            signals.append(f"The file's metadata says it was saved by editing software ({editor}).")

        modified = exif.get(306)
        taken = exif.get_ifd(0x8769).get(36867) if exif else None
        if modified and taken and str(modified).strip() != str(taken).strip():
            signals.append(f"The photo was changed after it was taken (taken {taken}, saved {modified}).")
    return signals


def error_level_image(file_path: str) -> Optional[bytes]:
    """Error level analysis picture of a JPEG bill, for a person to inspect.

    The photo is re-saved at quality 70 and the difference is amplified: text that was
    in the original photo glows evenly, while numbers pasted in later usually glow
    brighter or with a different texture than the text around them. Tests on our own
    bills showed the difference is visible but too small to decide automatically
    (genuine photos saved at other qualities reach similar values), so it is shown,
    not scored."""
    path = Path(file_path)
    if path.suffix.lower() not in (".jpg", ".jpeg") or not path.exists():
        return None
    with Image.open(path) as img:
        rgb = img.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=ELA_QUALITY)
    diff = np.asarray(ImageChops.difference(rgb, Image.open(io.BytesIO(buf.getvalue())).convert("RGB")).convert("L"),
                      dtype=np.float32)
    scale = 255.0 / max(float(np.percentile(diff, 99.9)), 1.0)
    gray = Image.fromarray(np.clip(diff * scale, 0, 255).astype(np.uint8))
    heat = ImageOps.colorize(gray, black="black", mid="#c2410c", white="#fde047")
    out = io.BytesIO()
    heat.save(out, "PNG")
    return out.getvalue()


def _pdf_text(value: bytes) -> str:
    if value.startswith(b"\xfe\xff"):  # UTF-16 text string
        return value[2:].decode("utf-16-be", "ignore")
    return value.decode("latin-1", "ignore")


def _pdf_signals(raw: bytes) -> list[str]:
    signals = []
    info = {k.decode(): _pdf_text(v)
            for k, v in re.findall(rb"/(Producer|Creator|CreationDate|ModDate)\s*\(((?:\\.|[^\\)])*)\)", raw, re.S)}
    editor = _editor_in(f"{info.get('Producer', '')} {info.get('Creator', '')}")
    if editor:
        signals.append(f"The PDF was produced or edited with {editor}.")

    created = re.sub(r"\D", "", info.get("CreationDate", ""))[:14]
    modified = re.sub(r"\D", "", info.get("ModDate", ""))[:14]
    if created and modified and modified > created:
        signals.append("The PDF was modified after it was first created.")

    saves = raw.count(b"%%EOF") - (1 if b"/Linearized" in raw else 0)
    if saves > 1:
        signals.append(f"The PDF was saved {saves} times: content was added after the original was made.")
    return signals


def tampering_signals(file_path: str) -> list[str]:
    path = Path(file_path)
    raw = path.read_bytes()
    if path.suffix.lower() == ".pdf":
        return _pdf_signals(raw)
    try:
        return _image_signals(path, raw)
    except Exception:  # unreadable image: OCR will already have failed or found nothing
        return []


# ---------------------------------------------------------------- hospital's record


# Characters OCR confuses in bill numbers; mapped the same way on both sides before comparing
_OCR_LOOKALIKES = str.maketrans("OILSBZ", "011582")
LINE_MATCH = 0.75      # similarity of two descriptions of the same line
AMOUNT_TOLERANCE = 1.0  # rupees


def bill_number_key(number: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", (number or "").upper()).translate(_OCR_LOOKALIKES)


def numbers_match(a: Optional[str], b: Optional[str]) -> bool:
    ka, kb = bill_number_key(a), bill_number_key(b)
    # exact after mapping lookalikes: CCH-2026-02011 and CCH-2026-02411 are different bills, however similar
    return bool(ka and kb) and ka == kb


def find_record(db: Session, hospital: Hospital, bill_number: Optional[str],
                exclude_id: Optional[int] = None) -> Optional[Bill]:
    """The bill the hospital itself submitted with this number (tolerating OCR misreads)."""
    key = bill_number_key(bill_number)
    if not key:
        return None
    query = select(Bill).where(Bill.hospital_id == hospital.id, Bill.verification_status == "hospital_uploaded",
                               Bill.bill_number.is_not(None))
    if exclude_id is not None:
        query = query.where(Bill.id != exclude_id)
    return next((record for record in db.scalars(query.order_by(Bill.id))
                 if bill_number_key(record.bill_number) == key), None)


def compare_with_record(items: list[dict], meta: dict, record: Bill) -> list[dict]:
    """Every difference between the patient's copy and the hospital's record of the same bill."""
    diffs = []
    for field, label in (("admission_date", "Admission date"), ("discharge_date", "Discharge date")):
        mine, theirs = parse_date(meta.get(field)), parse_date(getattr(record, field))
        if mine and theirs and mine != theirs:
            diffs.append({"kind": "date", "description": label, "copy": f"{mine:%d %b %Y}",
                          "record": f"{theirs:%d %b %Y}"})

    unmatched = list(range(len(items)))
    for line in record.items:
        scored = [(SequenceMatcher(None, _norm(items[i]["description"]), _norm(line.description)).ratio(), i)
                  for i in unmatched]
        score, best = max(scored, default=(0.0, None))
        if best is None or score < LINE_MATCH:
            diffs.append({"kind": "missing", "description": line.description, "copy": None, "record": line.amount})
            continue
        unmatched.remove(best)
        amount = float(items[best]["amount"])
        if abs(amount - line.amount) > AMOUNT_TOLERANCE:
            diffs.append({"kind": "amount", "description": line.description, "copy": amount, "record": line.amount})
    for i in unmatched:
        diffs.append({"kind": "added", "description": items[i]["description"], "copy": float(items[i]["amount"]),
                      "record": None})

    total = round(sum(float(i["amount"]) for i in items), 2)
    if abs(total - record.total_billed) > AMOUNT_TOLERANCE:
        diffs.append({"kind": "total", "description": "Total of the lines", "copy": total, "record": record.total_billed})
    return diffs


def reconcile(db: Session, patient: User, hospital: Optional[Hospital], items: list[dict], meta: dict,
              exclude_id: Optional[int] = None) -> Optional[dict]:
    """Look up the hospital's own copy of a bill a patient uploaded, and compare the two.
    None when there is nothing to look up (no registered hospital or no bill number)."""
    if hospital is None or not meta.get("bill_number"):
        return None
    record = find_record(db, hospital, meta["bill_number"], exclude_id)
    if record is None:
        return {"status": "not_found"}
    if record.patient_id != patient.id:  # never show another patient's bill
        return {"status": "other_patient", "record_number": record.bill_number}
    diffs = compare_with_record(items, meta, record)
    return {"status": "mismatch" if diffs else "matched", "record_id": record.id,
            "record_number": record.bill_number, "differences": diffs}


def _record_check(match: dict, hospital: Hospital, number: str) -> dict:
    name = "Matches the hospital's record"
    status = match["status"]
    if status == "matched":
        return _check("hospital_record", name, "pass",
                      f"{hospital.name}'s own bill {match['record_number']} (bill #{match['record_id']}) has the same "
                      f"dates, lines and amounts.")
    if status == "mismatch":
        n = len(match["differences"])
        first = match["differences"][0]
        return _check("hospital_record", name, "fail",
                      f"{n} difference(s) from {hospital.name}'s own bill {match['record_number']}, e.g. "
                      f"{first['description']}: {_show(first['copy'])} on this copy vs {_show(first['record'])} "
                      f"in the hospital's record.")
    if status == "other_patient":
        return _check("hospital_record", name, "fail",
                      f"{hospital.name}'s bill {match['record_number']} is for a different patient.")
    return _check("hospital_record", name, "waiting",
                  f"{hospital.name} has not submitted a bill numbered {number} yet. It will be compared automatically "
                  f"when they do, or the hospital can confirm it by hand.")


def _show(value) -> str:
    if value is None:
        return "nothing"
    return f"₹{value:,.0f}" if isinstance(value, (int, float)) else str(value)


# ---------------------------------------------------------------- checks


def _other_bills(exclude_ids=()):
    # a copy the patient deleted does not make their re-upload a repeat; the hospital's own records always count
    query = select(Bill).where(Bill.verification_status != "disputed",
                               or_(Bill.patient_deleted_at.is_(None), Bill.verification_status == "hospital_uploaded"))
    return query.where(Bill.id.not_in(exclude_ids)) if exclude_ids else query


def run_checks(db: Session, *, patient: User, hospital: Optional[Hospital], policy: Optional[Policy],
               items: list[dict], meta: dict, source: str, file_path: Optional[str],
               file_hash: Optional[str], content_hash: str, match: Optional[dict] = None,
               exclude_ids: tuple = ()) -> list[dict]:
    """exclude_ids: bills that are not repeats of this one even if they look the same: the
    hospital's record of a patient's copy, and other copies of that record."""
    checks = []
    printed = source != "manual"  # manual bills are typed in: there is no printed document to compare

    # 0. a patient's copy against the hospital's own record of the bill
    if match is not None:
        checks.append(_record_check(match, hospital, meta.get("bill_number") or ""))

    # 1. hospital on the bill = the hospital it was filed under
    printed_hospital = meta.get("hospital_name")
    if not printed:
        checks.append(_check("hospital_name", "Hospital name", "skip", "Entered by hand: no printed name to compare."))
    elif hospital is None:
        checks.append(_check("hospital_name", "Hospital name", "warn",
                             f"\"{printed_hospital or 'unknown'}\" is not a hospital registered on HealthBridge, "
                             f"so the bill cannot be confirmed with it."))
    elif not printed_hospital:
        checks.append(_check("hospital_name", "Hospital name", "warn", "No hospital name could be read from the bill."))
    else:
        score = name_similarity(printed_hospital, hospital.name)
        status = "pass" if score >= 0.85 else "warn" if score >= 0.6 else "fail"
        checks.append(_check("hospital_name", "Hospital name", status,
                             f"Bill says \"{printed_hospital}\"; filed under \"{hospital.name}\" "
                             f"({score * 100:.0f}% match)."))

    # 2. patient on the bill = the patient account
    printed_patient = meta.get("patient_name")
    if not printed:
        checks.append(_check("patient_name", "Patient name", "skip", "Entered by hand: no printed name to compare."))
    elif not printed_patient:
        checks.append(_check("patient_name", "Patient name", "warn", "No patient name could be read from the bill."))
    else:
        score = name_similarity(printed_patient, patient.full_name)
        status = "pass" if score >= 0.85 else "warn" if score >= 0.6 else "fail"
        checks.append(_check("patient_name", "Patient name", status,
                             f"Bill says \"{printed_patient}\"; account holder is \"{patient.full_name}\" "
                             f"({score * 100:.0f}% match)."))

    # 3. the same file uploaded before
    if file_hash:
        earlier = db.scalar(_other_bills(exclude_ids).where(Bill.file_hash == file_hash).order_by(Bill.id))
        checks.append(_check("duplicate_file", "File not uploaded before", "fail" if earlier else "pass",
                             f"Exactly the same file was already submitted as bill #{earlier.id}." if earlier
                             else "This file has not been submitted before."))

    # 4. bill number used before at this hospital
    number = (meta.get("bill_number") or "").strip()
    if number:
        query = _other_bills(exclude_ids).where(Bill.bill_number == number)
        if hospital is not None:
            query = query.where(Bill.hospital_id == hospital.id)
        else:
            query = query.where(Bill.hospital_name == printed_hospital)
        earlier = db.scalar(query.order_by(Bill.id))
        checks.append(_check("duplicate_bill_number", "Bill number not used before", "fail" if earlier else "pass",
                             f"Bill number {number} was already used by bill #{earlier.id} from this hospital."
                             if earlier else f"Bill number {number} is new for this hospital."))
    elif printed:
        checks.append(_check("duplicate_bill_number", "Bill number not used before", "warn",
                             "No bill number could be read; real hospital bills carry one."))

    # 5. the same bill entered again (re-photographed, re-typed, or a copy with a new number)
    has_dates = bool(meta.get("admission_date") or meta.get("discharge_date"))
    if has_dates or len(items) >= 3:
        earlier = db.scalar(_other_bills(exclude_ids).where(Bill.content_hash == content_hash).order_by(Bill.id))
        if earlier:
            # without dates, a short identical bill can be a genuine repeat visit: warn only
            checks.append(_check("duplicate_content", "Not a copy of another bill", "fail" if has_dates else "warn",
                                 f"Same hospital, dates, line items and amounts as bill #{earlier.id}."))
        else:
            checks.append(_check("duplicate_content", "Not a copy of another bill", "pass",
                                 "No earlier bill has the same lines and amounts."))

    # 6. dates are possible and inside the policy period
    admission, discharge = parse_date(meta.get("admission_date")), parse_date(meta.get("discharge_date"))
    today = datetime.now(timezone.utc).date()
    if not admission and not discharge:
        checks.append(_check("dates", "Treatment dates", "skip" if not printed else "warn",
                             "No dates given." if not printed else "No admission or discharge date could be read."))
    else:
        problems, notes = [], []
        if admission and discharge and discharge < admission:
            problems.append(f"discharge ({discharge:%d %b %Y}) is before admission ({admission:%d %b %Y})")
        latest = max(d for d in (admission, discharge) if d)
        earliest = min(d for d in (admission, discharge) if d)
        if latest > today:
            problems.append(f"{latest:%d %b %Y} is in the future")
        if (today - earliest).days > 365:
            notes.append(f"treatment on {earliest:%d %b %Y} is more than a year old")
        if policy is not None and earliest < policy.created_at.date():
            notes.append(f"treatment on {earliest:%d %b %Y} is before the policy started "
                         f"({policy.created_at:%d %b %Y})")
        status = "fail" if problems else "warn" if notes else "pass"
        found = "; ".join(problems + notes)
        detail = found[0].upper() + found[1:] + "." if found else (
            f"{earliest:%d %b %Y} to {latest:%d %b %Y}, within the policy period." if policy
            else f"{earliest:%d %b %Y} to {latest:%d %b %Y}.")
        checks.append(_check("dates", "Treatment dates", status, detail))

    # 7. signs that the file was edited
    if file_path and Path(file_path).exists():
        signals = tampering_signals(file_path)
        checks.append(_check("tampering", "No signs of editing", "warn" if signals else "pass",
                             " ".join(signals) if signals else
                             "The file's metadata shows no editing software or later changes."))
    return checks
