"""
Member 3's bill pipeline: upload/OCR -> parse -> detect -> cost split -> EMI -> recommendations,
plus the authenticity checks (services/verification.py) and hospital confirmation of
bills that patients upload themselves.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import ML_DIR, settings
from app.database import get_db
from app.models import Bill, BillItem, Claim, Hospital, Payment, Policy, User
from app.routers.patients import get_profile
from app.routers.policies import active_policy
from app.schemas import (
    BillDetailOut,
    BillSummaryOut,
    BillVerificationRequest,
    EMIRequest,
    ManualBillRequest,
    PaymentRequest,
    TextBillRequest,
)
from app.security import get_current_user, require_roles
from app.services import coverage, verification
from app.services.ml import OCRUnavailableError, registry

router = APIRouter(prefix="/api/bills", tags=["member 3 · bills & finance"])

ALLOWED_UPLOADS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".pdf"}
SAMPLE_DIR = ML_DIR / "bill" / "sample_data"


def _analyzer():
    if registry.bill is None:
        raise HTTPException(503, "The bill analyzer is not loaded. Check /api/health.")
    return registry.bill


def _resolve_parties(db: Session, uploader: User, patient_id: Optional[int], hospital_id: Optional[int]):
    if uploader.role == "hospital":
        if patient_id is None:
            raise HTTPException(422, "Choose the patient this bill belongs to.")
        patient = db.get(User, patient_id)
        if patient is None or patient.role != "patient":
            raise HTTPException(404, "Patient not found.")
        return patient, uploader.hospital
    hospital = db.get(Hospital, hospital_id) if hospital_id else None
    if hospital_id and hospital is None:
        raise HTTPException(404, "Hospital not found.")
    return uploader, hospital


def _policy_dict(db: Session, policy: Optional[Policy]) -> Optional[dict]:
    if policy is None:
        return None
    # the insurer's limit is what is left of the yearly sum insured, not the whole of it
    return {"deductible": policy.deductible, "co_insurance_pct": policy.co_insurance_pct,
            "copay_flat": policy.copay_flat, "room_rent_cap": policy.room_rent_cap,
            "sum_insured": coverage.left(db, policy)}


def _separate_sum_insured_limit(cost: dict, policy: Optional[Policy]) -> dict:
    """Member 3's calculator adds whatever is above the insurer's limit to the co-insurance share; show it
    on its own line, so the patient can see the year's sum insured ran out."""
    if policy is None:
        return cost
    co_insurance = round((cost["covered_amount"] - cost["deductible_applied"]) * policy.co_insurance_pct / 100, 2)
    over = round(cost["co_insurance_patient_share"] - co_insurance, 2)
    if over <= 0.01:
        return cost
    return {**cost, "co_insurance_patient_share": co_insurance, "sum_insured_shortfall": over}


def _duplicate_flags(items: list[dict], flags: list[dict]) -> list[Optional[dict]]:
    """Attach Member 3's duplicate flags to the right line. A flag names only the
    description, so with two identical lines it belongs to the second, never the first."""
    out, pending = [], list(flags)
    for i, item in enumerate(items):
        earlier = {x["description"] for x in items[:i]}
        mine = [f for f in pending if f["description"] == item["description"] and f["matched_with"] in earlier]
        for f in mine:
            pending.remove(f)
        out.append(mine[0] if mine else None)
    return out


def _create_bill(db: Session, uploader: User, patient: User, hospital: Optional[Hospital], items: list[dict],
                 source: str, meta: dict, raw_text: Optional[str] = None, file_path: Optional[str] = None,
                 file_hash: Optional[str] = None, record_only: bool = False) -> Bill:
    if not items:
        raise HTTPException(422, "No line items could be read from this bill. Check the image quality or "
                                 "enter the items manually.")
    analyzer = _analyzer()
    city_tier = hospital.city_tier if hospital else "tier2"
    hospital_type = hospital.hospital_type if hospital else "private"
    policy = active_policy(db, patient.id)
    profile = get_profile(db, patient)

    result = analyzer.analyze(
        items, city_tier, hospital_type, _policy_dict(db, policy),
        {"monthly_income": profile.monthly_income, "existing_monthly_debt": profile.existing_monthly_debt,
         "has_credit_card": profile.has_credit_card},
    )
    detection, cost = result["detection"], _separate_sum_insured_limit(result["cost_breakdown"], policy)
    duplicates = _duplicate_flags(items, detection["duplicate_charges"])

    hospital_name = meta.get("hospital_name") or (hospital.name if hospital else None)
    hospital_key = f"h{hospital.id}" if hospital else verification._norm(hospital_name)
    content_hash = verification.content_fingerprint(items, hospital_key, meta.get("admission_date"),
                                                    meta.get("discharge_date"))
    authenticity = _assess(db, uploader.role, patient, hospital, policy, items, meta, source, file_path, file_hash,
                           content_hash)
    _refuse_other_hospitals_bill(db, uploader, hospital, meta)
    _refuse_other_patients_bill(uploader, patient, meta, authenticity)

    bill = Bill(
        patient_id=patient.id, hospital_id=hospital.id if hospital else None,
        policy_id=policy.id if policy else None, uploaded_by=uploader.id, source=source,
        file_path=file_path, raw_text=raw_text, hospital_name=hospital_name,
        bill_number=meta.get("bill_number"), admission_date=meta.get("admission_date"),
        discharge_date=meta.get("discharge_date"), city_tier=city_tier, hospital_type=hospital_type,
        stated_total=meta.get("stated_total"), total_billed=cost["total_billed"],
        total_mismatch=bool(meta.get("total_mismatch")), insurance_pays=cost["insurance_pays"],
        patient_out_of_pocket=cost["patient_out_of_pocket"],
        flagged_amount=detection["summary"]["flagged_amount_total"],
        duplicate_count=detection["summary"]["duplicate_count"],
        high_risk_count=detection["summary"]["high_risk_count"],
        cost_breakdown=cost, emi=result["emi"], recommendations=result["recommendations"],
        payment_status="paid" if cost["patient_out_of_pocket"] == 0 else "unpaid",
        printed_patient_name=meta.get("patient_name"), file_hash=file_hash, content_hash=content_hash,
        **authenticity, record_only=True if record_only and uploader.role == "hospital" else None,
    )
    for item, scored, dup in zip(items, detection["ml_price_analysis"], duplicates):
        bill.items.append(BillItem(
            description=item["description"], category=item["category"], amount=item["amount"],
            quantity=item["quantity"], is_covered=bool(policy) and item["is_covered"],
            fair_price=scored["fair_price_predicted"], overcharge_pct=scored["overcharge_pct"],
            ml_anomaly=scored["ml_anomaly"], severity=scored["severity"],
            duplicate_of=dup["matched_with"] if dup else None,
            duplicate_similarity=dup["similarity_pct"] if dup else None,
        ))
    _reveal_matched_record(db, authenticity["match_result"])
    db.add(bill)
    db.commit()
    db.refresh(bill)
    if uploader.role == "hospital" and bill.bill_number:
        _recheck_waiting_copies(db, bill)
    return bill


def shared_with_patient():
    """Bills shared beyond the hospital: everything except hospital-only records."""
    return or_(Bill.record_only.is_(None), Bill.record_only.is_(False))


def visible_to_patient():
    """Bills in the patient's account: shared with them and not deleted by them."""
    return and_(shared_with_patient(), Bill.patient_deleted_at.is_(None))


def _reveal_matched_record(db: Session, match: Optional[dict]):
    """The patient's copy matches the hospital's hidden record exactly: the record now appears in
    their account, and the claim is filed on it."""
    if match and match["status"] == "matched":
        record = db.get(Bill, match["record_id"])
        if record is not None and record.record_only:
            record.record_only = False


def _refuse_other_hospitals_bill(db: Session, uploader: User, hospital: Optional[Hospital], meta: dict):
    """A bill printed by another hospital on HealthBridge is filed with that hospital, not this one: usually
    the wrong hospital was chosen. Refused, nothing saved, and the message names the right hospital. A name
    that matches no registered hospital is only flagged by the Hospital name check."""
    printed = meta.get("hospital_name")
    if hospital is None or not printed or verification.name_similarity(printed, hospital.name) >= 0.6:
        return
    other = max(db.scalars(select(Hospital).where(Hospital.id != hospital.id)),
                key=lambda h: verification.name_similarity(printed, h.name), default=None)
    if other is None or verification.name_similarity(printed, other.name) < 0.85:
        return
    if uploader.role == "hospital":
        raise HTTPException(422, f"This bill was issued by {other.name}, not {hospital.name}. A hospital can only "
                                 f"add its own bills.")
    raise HTTPException(422, f"This bill is from {other.name}, but you chose {hospital.name}. Choose {other.name} "
                             f"and upload it again.")


def _refuse_other_patients_bill(uploader: User, patient: User, meta: dict, authenticity: dict):
    """A bill can only be added to the account of the patient it was issued to. Small OCR
    misreadings of the name only warn; a clearly different name, or a bill number the hospital
    issued to someone else, is refused and nothing is saved."""
    checks = {c["key"]: c for c in authenticity["checks"]}
    if checks.get("patient_name", {}).get("status") == "fail":
        printed = meta.get("patient_name")
        if uploader.role == "patient":
            raise HTTPException(422, f"This bill is for \"{printed}\", not {patient.full_name}. You can only add "
                                     f"bills issued to you.")
        raise HTTPException(422, f"This bill is for \"{printed}\", not {patient.full_name}. Choose the patient named "
                                 f"on the bill.")
    match = authenticity["match_result"]
    if match and match["status"] == "other_patient":
        raise HTTPException(422, f"Bill {match['record_number']} was issued by the hospital to a different patient. "
                                 f"You can only add bills issued to you.")


def _assess(db: Session, uploader_role: str, patient: User, hospital: Optional[Hospital], policy: Optional[Policy],
            items: list[dict], meta: dict, source: str, file_path: Optional[str], file_hash: Optional[str],
            content_hash: str, bill_id: Optional[int] = None) -> dict:
    """Authenticity fields for a bill: the checks, and for a patient's upload the comparison
    with the hospital's own record of it."""
    match, exclude = None, ()
    if uploader_role == "hospital" and hospital and meta.get("bill_number"):
        # patients' copies waiting for this bill are not repeats of it: they are compared with it next
        exclude = tuple(_waiting_copies(db, hospital.id, meta["bill_number"], bill_id))
    if uploader_role == "patient":
        match = verification.reconcile(db, patient, hospital, items, meta, exclude_id=bill_id)
        if match and match.get("record_id"):
            copies = db.scalars(select(Bill.id).where(Bill.matched_bill_id == match["record_id"])).all()
            exclude = (match["record_id"], *copies)
    if bill_id is not None:
        exclude = (*exclude, bill_id)
    checks = verification.run_checks(
        db, patient=patient, hospital=hospital, policy=policy, items=items, meta=meta, source=source,
        file_path=file_path, file_hash=file_hash, content_hash=content_hash, match=match, exclude_ids=exclude,
    )
    if uploader_role == "hospital":
        status = "hospital_uploaded"  # the provider itself vouches for the bill
    elif match and match["status"] in verification.COPIES:
        status = match["status"]
    else:
        status = "pending" if hospital else "unverifiable"
    return {"checks": checks, "authenticity": verification.overall(checks), "verification_status": status,
            "matched_bill_id": match.get("record_id") if match else None, "match_result": match}


def _waiting_copies(db: Session, hospital_id: int, bill_number: str, exclude_id: Optional[int] = None) -> list[int]:
    """Bills patients uploaded under this hospital and bill number that are still waiting for it."""
    query = select(Bill).where(Bill.hospital_id == hospital_id, Bill.verification_status == "pending",
                               Bill.bill_number.is_not(None))
    if exclude_id is not None:
        query = query.where(Bill.id != exclude_id)
    return [b.id for b in db.scalars(query) if verification.numbers_match(b.bill_number, bill_number)]


def _recheck_waiting_copies(db: Session, record: Bill):
    """A hospital just submitted a bill: compare it with any copy a patient uploaded earlier."""
    for copy_id in _waiting_copies(db, record.hospital_id, record.bill_number, record.id):
        copy = db.get(Bill, copy_id)
        items = [{"description": i.description, "amount": i.amount, "category": i.category, "quantity": i.quantity}
                 for i in copy.items]
        meta = {"hospital_name": copy.hospital_name, "patient_name": copy.printed_patient_name,
                "bill_number": copy.bill_number, "admission_date": copy.admission_date,
                "discharge_date": copy.discharge_date}
        policy = db.get(Policy, copy.policy_id) if copy.policy_id else None
        fields = _assess(db, "patient", copy.patient, copy.hospital, policy, items, meta, copy.source, copy.file_path,
                         copy.file_hash, copy.content_hash, bill_id=copy.id)
        for key, value in fields.items():
            setattr(copy, key, value)
        _reveal_matched_record(db, fields["match_result"])
    db.commit()


def _from_text(db: Session, uploader: User, patient_id, hospital_id, raw_text: str, source: str,
               file_path: Optional[str] = None, file_hash: Optional[str] = None, record_only: bool = False) -> Bill:
    patient, hospital = _resolve_parties(db, uploader, patient_id, hospital_id)
    parsed = _analyzer().parse(raw_text)
    meta = {k: parsed[k] for k in ("hospital_name", "patient_name", "bill_number", "admission_date",
                                   "discharge_date", "stated_total", "total_mismatch")}
    return _create_bill(db, uploader, patient, hospital, parsed["line_items"], source, meta, raw_text, file_path,
                        file_hash, record_only)


def _scoped(user: User):
    query = select(Bill)
    shared = shared_with_patient()  # hospital-only records stay hidden
    if user.role == "patient":
        return query.where(Bill.patient_id == user.id, visible_to_patient())
    if user.role == "hospital":
        return query.where(Bill.hospital_id == user.hospital.id)
    if user.role == "insurer":
        return query.where(shared, Bill.policy_id.in_(select(Policy.id).where(Policy.insurer_id == user.insurer.id)))
    return query


def _get_bill(db: Session, user: User, bill_id: int) -> Bill:
    bill = db.scalar(_scoped(user).where(Bill.id == bill_id))
    if bill is None:
        raise HTTPException(404, "Bill not found.")
    return bill


def _latest_claim(db: Session, bill_id: int) -> Optional[Claim]:
    return db.scalar(select(Claim).where(Claim.bill_id == bill_id).order_by(Claim.submitted_at.desc()))


def claim_bill_id(bill: Bill) -> int:
    """The bill a claim is filed on: a patient's matching copy is claimed through the hospital's record."""
    return bill.matched_bill_id if bill.verification_status == "matched" and bill.matched_bill_id else bill.id


def summary_out(db: Session, bill: Bill) -> BillSummaryOut:
    out = BillSummaryOut.model_validate(bill)
    out.patient_name = bill.patient.full_name
    out.registered_hospital = bill.hospital.name if bill.hospital else None
    claim = _latest_claim(db, claim_bill_id(bill))
    out.claim_status = claim.status if claim else None
    return out


def detail_out(db: Session, bill: Bill) -> BillDetailOut:
    out = BillDetailOut.model_validate(bill)
    out.patient_name = bill.patient.full_name
    out.registered_hospital = bill.hospital.name if bill.hospital else None
    claim = _latest_claim(db, claim_bill_id(bill))
    out.claim_status = claim.status if claim else None
    out.claim_id = claim.id if claim else None
    out.error_level_available = bool(bill.file_path) and Path(bill.file_path).suffix.lower() in (".jpg", ".jpeg")
    payment = db.scalar(select(Payment).where(Payment.bill_id == bill.id).order_by(Payment.created_at.desc()))
    if payment:
        out.payment = {"plan": payment.plan, "principal": payment.principal, "annual_rate": payment.annual_rate,
                       "tenure_months": payment.tenure_months, "monthly_emi": payment.monthly_emi,
                       "total_payment": payment.total_payment, "created_at": payment.created_at.isoformat()}
    return out


# ---------------------------------------------------------------- create


@router.post("/upload", response_model=BillDetailOut, status_code=201,
             summary="Upload a bill image or PDF (OCR pipeline)")
async def upload_bill(
    file: UploadFile = File(...),
    patient_id: Optional[int] = Form(None),
    hospital_id: Optional[int] = Form(None),
    record_only: bool = Form(False),
    user: User = Depends(require_roles("patient", "hospital")),
    db: Session = Depends(get_db),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_UPLOADS:
        raise HTTPException(422, "Upload a PNG, JPG, TIFF, BMP or PDF file.")
    limit = int(settings.max_upload_mb * 1024 * 1024)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"The file is larger than {settings.max_upload_mb:g} MB.")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    stored = settings.upload_dir / f"{uuid.uuid4().hex}{suffix}"
    stored.write_bytes(data)
    try:
        raw_text = _analyzer().ocr(str(stored))
    except OCRUnavailableError as exc:
        stored.unlink(missing_ok=True)
        raise HTTPException(503, str(exc))
    except Exception:
        stored.unlink(missing_ok=True)
        raise HTTPException(422, "This file could not be read as an image or PDF.")
    try:
        bill = _from_text(db, user, patient_id, hospital_id, raw_text, "ocr", str(stored), verification.sha256(data),
                          record_only)
    except HTTPException:
        stored.unlink(missing_ok=True)
        raise
    return detail_out(db, bill)


@router.post("/sample", response_model=BillDetailOut, status_code=201,
             summary="Run the pipeline on Member 3's sample hospital bill")
def sample_bill(
    patient_id: Optional[int] = Form(None),
    hospital_id: Optional[int] = Form(None),
    user: User = Depends(require_roles("patient", "hospital")),
    db: Session = Depends(get_db),
):
    analyzer = _analyzer()
    image = SAMPLE_DIR / "sample_bill_1.png"
    if analyzer.ocr_available():
        raw_text, source = analyzer.ocr(str(image)), "ocr"
    else:  # the OCR text Member 3's pipeline recorded for this image
        raw_text, source = (SAMPLE_DIR / "sample_bill_1.txt").read_text(encoding="utf-8"), "text"
    file_hash = verification.sha256(image.read_bytes())
    return detail_out(db, _from_text(db, user, patient_id, hospital_id, raw_text, source, str(image), file_hash))


@router.post("/text", response_model=BillDetailOut, status_code=201, summary="Analyse pasted bill text")
def text_bill(body: TextBillRequest, user: User = Depends(require_roles("patient", "hospital")),
              db: Session = Depends(get_db)):
    return detail_out(db, _from_text(db, user, body.patient_id, body.hospital_id, body.raw_text, "text",
                                     record_only=body.record_only))


@router.post("/manual", response_model=BillDetailOut, status_code=201, summary="Enter line items by hand")
def manual_bill(body: ManualBillRequest, user: User = Depends(require_roles("patient", "hospital")),
                db: Session = Depends(get_db)):
    patient, hospital = _resolve_parties(db, user, body.patient_id, body.hospital_id)
    analyzer = _analyzer()
    items = [analyzer.describe_item(i.description, i.amount, i.quantity, i.category) for i in body.items]
    meta = {"bill_number": body.bill_number, "admission_date": body.admission_date,
            "discharge_date": body.discharge_date}
    return detail_out(db, _create_bill(db, user, patient, hospital, items, "manual", meta, record_only=body.record_only))


# ---------------------------------------------------------------- read


@router.get("", response_model=list[BillSummaryOut])
def list_bills(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bills = db.scalars(_scoped(user).order_by(Bill.created_at.desc())).all()
    return [summary_out(db, b) for b in bills]


@router.get("/{bill_id}", response_model=BillDetailOut)
def read_bill(bill_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return detail_out(db, _get_bill(db, user, bill_id))


@router.get("/{bill_id}/error-level", summary="Error level analysis picture of a photographed (JPEG) bill",
            response_class=Response, responses={200: {"content": {"image/png": {}}}})
def error_level(bill_id: int, user: User = Depends(require_roles("hospital", "insurer", "finance", "admin")),
                db: Session = Depends(get_db)):
    bill = _get_bill(db, user, bill_id)
    image = verification.error_level_image(bill.file_path) if bill.file_path else None
    if image is None:
        raise HTTPException(404, "Error level analysis is only available for bills uploaded as JPEG photos.")
    return Response(image, media_type="image/png")


# ---------------------------------------------------------------- verify


@router.delete("/{bill_id}", status_code=204, summary="Patient: delete a bill from your account (the hospital keeps it)")
def delete_bill(bill_id: int, user: User = Depends(require_roles("patient")), db: Session = Depends(get_db)):
    bill = _get_bill(db, user, bill_id)
    claim = db.scalar(select(Claim).where(Claim.bill_id.in_([bill.id, bill.matched_bill_id or -1]),
                                          Claim.status.in_(("submitted", "approved"))))
    if claim is not None:
        raise HTTPException(409, f"Claim {claim.claim_number} on this bill is still open. The bill can be deleted "
                                 "once the insurer has settled or rejected it.")
    bill.patient_deleted_at = datetime.now(timezone.utc)
    db.commit()
    return Response(status_code=204)


@router.post("/{bill_id}/verification", response_model=BillDetailOut,
             summary="Hospital confirms or disputes a bill that a patient uploaded")
def verify_bill(bill_id: int, body: BillVerificationRequest, user: User = Depends(require_roles("hospital")),
                db: Session = Depends(get_db)):
    bill = _get_bill(db, user, bill_id)
    if bill.verification_status != "pending":
        raise HTTPException(409, "Only bills awaiting your confirmation can be confirmed or disputed.")
    if body.action == "dispute" and not (body.note or "").strip():
        raise HTTPException(422, "Say why the bill is disputed, so the patient and insurer know.")
    bill.verification_status = "confirmed" if body.action == "confirm" else "disputed"
    bill.verification_note = (body.note or "").strip() or None
    bill.verified_at = datetime.now(timezone.utc)
    db.commit()
    return detail_out(db, bill)


# ---------------------------------------------------------------- pay


@router.post("/{bill_id}/emi", summary="Preview an EMI plan for this bill's out-of-pocket amount")
def preview_emi(bill_id: int, body: EMIRequest, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    bill = _get_bill(db, user, bill_id)
    if bill.patient_out_of_pocket <= 0:
        raise HTTPException(422, "Nothing is owed on this bill.")
    return _analyzer().emi(bill.patient_out_of_pocket, body.annual_rate, body.months)


@router.post("/{bill_id}/pay", response_model=BillDetailOut, summary="Choose to pay in full or on EMI")
def pay_bill(bill_id: int, body: PaymentRequest, user: User = Depends(require_roles("patient")),
             db: Session = Depends(get_db)):
    bill = _get_bill(db, user, bill_id)
    if bill.payment_status != "unpaid":
        raise HTTPException(409, "A payment plan is already recorded for this bill.")
    principal = bill.patient_out_of_pocket
    if body.plan == "full":
        payment = Payment(bill_id=bill.id, patient_id=user.id, plan="full", principal=principal, annual_rate=0,
                          tenure_months=1, monthly_emi=principal, total_payment=principal, schedule=[])
        bill.payment_status = "paid"
    else:
        emi = _analyzer().emi(principal, body.annual_rate, body.months)
        payment = Payment(bill_id=bill.id, patient_id=user.id, plan="emi", principal=principal,
                          annual_rate=body.annual_rate, tenure_months=body.months, monthly_emi=emi["monthly_emi"],
                          total_payment=emi["total_payment"], schedule=emi["schedule"])
        bill.payment_status = "on_emi"
    db.add(payment)
    db.commit()
    return detail_out(db, bill)
