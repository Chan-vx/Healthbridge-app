"""Insurance claims, scored by Member 2's hybrid fraud engine at submission."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.database import get_db
from app.models import Bill, Claim, Policy, User
from app.routers.bills import _get_bill
from app.routers.patients import get_profile
from app.schemas import ClaimDecision, ClaimOut, ClaimRequest
from app.security import get_current_user, require_roles
from app.services import coverage
from app.services.claim_decision import recommend
from app.services.ml import registry
from app.services.verification import DUPLICATE_CHECKS

router = APIRouter(prefix="/api/claims", tags=["member 2 · claims & fraud"])

RISK_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def claim_out(c: Claim) -> ClaimOut:
    out = ClaimOut.model_validate(c)
    out.patient_name = c.patient.full_name
    out.hospital_name = c.hospital.name if c.hospital else None
    out.insurer_name = c.insurer.name
    out.fraud_threshold = registry.fraud.threshold if registry.fraud else None
    out.advice = recommend(c)
    if c.policy is not None:
        # what the policy has left for this claim (the claim itself not counted)
        out.coverage = coverage.usage(object_session(c), c.policy, exclude_claim_id=c.id)
    return out


NOT_CLAIMABLE = {
    "pending": "The hospital has not confirmed this bill yet. A claim can be filed once it does.",
    "disputed": "The hospital disputed this bill, so it cannot be claimed.",
    "unverifiable": "This bill is from a hospital that is not on HealthBridge, so it cannot be confirmed or claimed.",
}


def _ensure_claimable(bill: Bill):
    if bill.verification_status == "mismatch":
        raise HTTPException(422, "This copy differs from the hospital's own record of the bill, so it cannot be "
                                 "claimed.")
    if bill.verification_status in NOT_CLAIMABLE:
        raise HTTPException(422, NOT_CLAIMABLE[bill.verification_status])
    copy = next((c for c in bill.checks or [] if c["key"] in DUPLICATE_CHECKS and c["status"] == "fail"), None)
    if copy:
        raise HTTPException(422, f"This bill repeats an earlier one, so it cannot be claimed: {copy['detail']}")


def _scoped(user: User):
    query = select(Claim)
    if user.role == "patient":
        return query.where(Claim.patient_id == user.id)
    if user.role == "hospital":
        return query.where(Claim.hospital_id == user.hospital.id)
    if user.role == "insurer":
        return query.where(Claim.insurer_id == user.insurer.id)
    return query


@router.post("", response_model=ClaimOut, status_code=201)
def submit_claim(body: ClaimRequest, user: User = Depends(require_roles("hospital", "patient")),
                 db: Session = Depends(get_db)):
    if registry.fraud is None:
        raise HTTPException(503, "The fraud model is not loaded. Check /api/health.")
    bill: Bill = _get_bill(db, user, body.bill_id)
    if bill.verification_status == "matched" and bill.matched_bill_id:
        bill = _get_bill(db, user, bill.matched_bill_id)  # a matching copy is claimed through the hospital's record
    if bill.policy_id is None:
        raise HTTPException(422, "This patient had no active insurance policy when the bill was analysed.")
    if bill.insurance_pays <= 0:
        raise HTTPException(422, "Insurance covers nothing on this bill, so there is nothing to claim.")
    _ensure_claimable(bill)
    bill.record_only = None  # once claimed, the patient and insurer see the bill
    existing = db.scalar(select(Claim).where(Claim.bill_id == bill.id, Claim.status != "rejected"))
    if existing:
        raise HTTPException(409, f"Claim {existing.claim_number} already exists for this bill.")

    policy = db.get(Policy, bill.policy_id)
    # the sum insured is yearly: claims filed since this bill was analysed may have used some of it
    available = coverage.left(db, policy)
    if available <= 0:
        raise HTTPException(422, f"The sum insured of policy {policy.policy_number} is used up for this policy year; "
                                 "nothing more can be claimed until it renews.")
    if bill.insurance_pays > available:
        shortfall = round(bill.insurance_pays - available, 2)
        bill.insurance_pays = available
        bill.patient_out_of_pocket = round(bill.patient_out_of_pocket + shortfall, 2)
        bill.cost_breakdown = {**(bill.cost_breakdown or {}), "insurance_pays": available,
                               "patient_out_of_pocket": bill.patient_out_of_pocket, "sum_insured_shortfall": shortfall}
        if bill.payment_status == "paid":
            bill.payment_status = "unpaid"
    profile = get_profile(db, bill.patient)
    now = datetime.now(timezone.utc)
    location = bill.hospital.city if bill.hospital and bill.hospital.city else "Unknown"
    score = registry.fraud.score(
        claim_amount_inr=bill.insurance_pays, patient_age=profile.age, patient_sex=profile.sex,
        annual_income_inr=profile.monthly_income * 12, marital_status=profile.marital_status,
        employment_status=profile.employment_status, provider_specialty=body.provider_specialty,
        provider_location=location, claim_type=body.claim_type, submission_method=body.submission_method,
        claim_date=now,
    )
    claim = Claim(
        claim_number="pending", bill_id=bill.id, patient_id=bill.patient_id, hospital_id=bill.hospital_id,
        insurer_id=policy.insurer_id, policy_id=policy.id, submitted_by=user.id,
        claim_amount=bill.insurance_pays, claim_type=body.claim_type, provider_specialty=body.provider_specialty,
        submission_method=body.submission_method, provider_location=location,
        fraud_probability=score["fraud_probability"], anomaly_score=score["anomaly_score"],
        hybrid_risk_score=score["hybrid_risk_score"], fraud_prediction=score["fraud_prediction"],
        risk_level=score["risk_level"], recommendation=score["recommendation"],
        top_factors=score["top_factors"], model_inputs=score["model_inputs"], submitted_at=now,
    )
    db.add(claim)
    db.flush()
    claim.claim_number = f"CLM-{now.year}-{claim.id:05d}"
    db.commit()
    db.refresh(claim)
    return claim_out(claim)


@router.get("", response_model=list[ClaimOut])
def list_claims(status: Optional[str] = None, risk: Optional[str] = None,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = _scoped(user)
    if status:  # one status or several, comma-separated: ?status=approved,settled,rejected
        query = query.where(Claim.status.in_([s.strip() for s in status.split(",") if s.strip()]))
    if risk:
        query = query.where(Claim.risk_level == risk.upper())
    claims = db.scalars(query.order_by(Claim.submitted_at.desc())).all()
    if user.role == "insurer":  # investigation queue: open claims first, highest risk first
        claims.sort(key=lambda c: (c.status != "submitted", RISK_ORDER.get(c.risk_level, 3), -c.hybrid_risk_score))
    return [claim_out(c) for c in claims]


@router.get("/{claim_id}", response_model=ClaimOut)
def read_claim(claim_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    claim = db.scalar(_scoped(user).where(Claim.id == claim_id))
    if claim is None:
        raise HTTPException(404, "Claim not found.")
    return claim_out(claim)


@router.post("/{claim_id}/decision", response_model=ClaimOut)
def decide_claim(claim_id: int, body: ClaimDecision, user: User = Depends(require_roles("insurer")),
                 db: Session = Depends(get_db)):
    claim = db.scalar(_scoped(user).where(Claim.id == claim_id))
    if claim is None:
        raise HTTPException(404, "Claim not found.")

    allowed = {"approve": "submitted", "reject": "submitted", "settle": "approved"}
    if claim.status != allowed[body.action]:
        past = {"approve": "approved", "reject": "rejected", "settle": "settled"}[body.action]
        raise HTTPException(409, f"A claim that is '{claim.status}' cannot be {past}.")

    if body.action == "approve":
        amount = claim.claim_amount if body.approved_amount is None else body.approved_amount
        if amount > claim.claim_amount:
            raise HTTPException(422, "The approved amount cannot exceed the claimed amount.")
        available = coverage.left(db, claim.policy, exclude_claim_id=claim.id)
        if amount > available:
            raise HTTPException(422, f"Only ₹{available:,.0f} of the sum insured is left this policy year; "
                                     "approve that amount or less.")
        claim.status, claim.approved_amount = "approved", amount
    elif body.action == "reject":
        claim.status, claim.approved_amount = "rejected", 0.0
    else:
        claim.status = "settled"
    if body.note:
        claim.decision_note = body.note
    claim.decided_at = datetime.now(timezone.utc)
    db.commit()
    return claim_out(claim)
