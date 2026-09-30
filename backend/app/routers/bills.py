"""Member 3's bill pipeline: upload/OCR -> parse -> detect -> cost split -> EMI -> recommendations."""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import ML_DIR, settings
from app.database import get_db
from app.models import Bill, BillItem, Claim, Hospital, Payment, Policy, User
from app.routers.patients import get_profile
from app.routers.policies import active_policy
from app.schemas import (
    BillDetailOut,
    BillSummaryOut,
    EMIRequest,
    ManualBillRequest,
    PaymentRequest,
    TextBillRequest,
)
from app.security import get_current_user, require_roles
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


def _policy_dict(policy: Optional[Policy]) -> Optional[dict]:
    if policy is None:
        return None
    return {"deductible": policy.deductible, "co_insurance_pct": policy.co_insurance_pct,
            "copay_flat": policy.copay_flat, "room_rent_cap": policy.room_rent_cap,
            "sum_insured": policy.sum_insured}


def _create_bill(db: Session, uploader: User, patient: User, hospital: Optional[Hospital], items: list[dict],
                 source: str, meta: dict, raw_text: Optional[str] = None, file_path: Optional[str] = None) -> Bill:
    if not items:
        raise HTTPException(422, "No line items could be read from this bill. Check the image quality or "
                                 "enter the items manually.")
    analyzer = _analyzer()
    city_tier = hospital.city_tier if hospital else "tier2"
    hospital_type = hospital.hospital_type if hospital else "private"
    policy = active_policy(db, patient.id)
    profile = get_profile(db, patient)

    result = analyzer.analyze(
        items, city_tier, hospital_type, _policy_dict(policy),
        {"monthly_income": profile.monthly_income, "existing_monthly_debt": profile.existing_monthly_debt,
         "has_credit_card": profile.has_credit_card},
    )
    detection, cost = result["detection"], result["cost_breakdown"]
    duplicates = {d["description"]: d for d in detection["duplicate_charges"]}

    bill = Bill(
        patient_id=patient.id, hospital_id=hospital.id if hospital else None,
        policy_id=policy.id if policy else None, uploaded_by=uploader.id, source=source,
        file_path=file_path, raw_text=raw_text,
        hospital_name=meta.get("hospital_name") or (hospital.name if hospital else None),
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
    )
    for item, scored in zip(items, detection["ml_price_analysis"]):
        dup = duplicates.get(item["description"])
        bill.items.append(BillItem(
            description=item["description"], category=item["category"], amount=item["amount"],
            quantity=item["quantity"], is_covered=bool(policy) and item["is_covered"],
            fair_price=scored["fair_price_predicted"], overcharge_pct=scored["overcharge_pct"],
            ml_anomaly=scored["ml_anomaly"], severity=scored["severity"],
            duplicate_of=dup["matched_with"] if dup else None,
            duplicate_similarity=dup["similarity_pct"] if dup else None,
        ))
    db.add(bill)
    db.commit()
    db.refresh(bill)
    return bill


def _from_text(db: Session, uploader: User, patient_id, hospital_id, raw_text: str, source: str,
               file_path: Optional[str] = None) -> Bill:
    patient, hospital = _resolve_parties(db, uploader, patient_id, hospital_id)
    parsed = _analyzer().parse(raw_text)
    meta = {k: parsed[k] for k in ("hospital_name", "bill_number", "admission_date", "discharge_date",
                                   "stated_total", "total_mismatch")}
    return _create_bill(db, uploader, patient, hospital, parsed["line_items"], source, meta, raw_text, file_path)


def _scoped(user: User):
    query = select(Bill)
    if user.role == "patient":
        return query.where(Bill.patient_id == user.id)
    if user.role == "hospital":
        return query.where(Bill.hospital_id == user.hospital.id)
    if user.role == "insurer":
        return query.where(Bill.policy_id.in_(select(Policy.id).where(Policy.insurer_id == user.insurer.id)))
    return query


def _get_bill(db: Session, user: User, bill_id: int) -> Bill:
    bill = db.scalar(_scoped(user).where(Bill.id == bill_id))
    if bill is None:
        raise HTTPException(404, "Bill not found.")
    return bill


def _latest_claim(db: Session, bill_id: int) -> Optional[Claim]:
    return db.scalar(select(Claim).where(Claim.bill_id == bill_id).order_by(Claim.submitted_at.desc()))


def summary_out(db: Session, bill: Bill) -> BillSummaryOut:
    out = BillSummaryOut.model_validate(bill)
    out.patient_name = bill.patient.full_name
    claim = _latest_claim(db, bill.id)
    out.claim_status = claim.status if claim else None
    return out


def detail_out(db: Session, bill: Bill) -> BillDetailOut:
    out = BillDetailOut.model_validate(bill)
    out.patient_name = bill.patient.full_name
    claim = _latest_claim(db, bill.id)
    out.claim_status = claim.status if claim else None
    out.claim_id = claim.id if claim else None
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
    user: User = Depends(require_roles("patient", "hospital")),
    db: Session = Depends(get_db),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_UPLOADS:
        raise HTTPException(422, "Upload a PNG, JPG, TIFF, BMP or PDF file.")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    stored = settings.upload_dir / f"{uuid.uuid4().hex}{suffix}"
    stored.write_bytes(await file.read())
    try:
        raw_text = _analyzer().ocr(str(stored))
    except OCRUnavailableError as exc:
        raise HTTPException(503, str(exc))
    return detail_out(db, _from_text(db, user, patient_id, hospital_id, raw_text, "ocr", str(stored)))


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
    return detail_out(db, _from_text(db, user, patient_id, hospital_id, raw_text, source, str(image)))


@router.post("/text", response_model=BillDetailOut, status_code=201, summary="Analyse pasted bill text")
def text_bill(body: TextBillRequest, user: User = Depends(require_roles("patient", "hospital")),
              db: Session = Depends(get_db)):
    return detail_out(db, _from_text(db, user, body.patient_id, body.hospital_id, body.raw_text, "text"))


@router.post("/manual", response_model=BillDetailOut, status_code=201, summary="Enter line items by hand")
def manual_bill(body: ManualBillRequest, user: User = Depends(require_roles("patient", "hospital")),
                db: Session = Depends(get_db)):
    patient, hospital = _resolve_parties(db, user, body.patient_id, body.hospital_id)
    analyzer = _analyzer()
    items = [analyzer.describe_item(i.description, i.amount, i.quantity, i.category) for i in body.items]
    meta = {"bill_number": body.bill_number, "admission_date": body.admission_date,
            "discharge_date": body.discharge_date}
    return detail_out(db, _create_bill(db, user, patient, hospital, items, "manual", meta))


# ---------------------------------------------------------------- read


@router.get("", response_model=list[BillSummaryOut])
def list_bills(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bills = db.scalars(_scoped(user).order_by(Bill.created_at.desc())).all()
    return [summary_out(db, b) for b in bills]


@router.get("/{bill_id}", response_model=BillDetailOut)
def read_bill(bill_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return detail_out(db, _get_bill(db, user, bill_id))


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
