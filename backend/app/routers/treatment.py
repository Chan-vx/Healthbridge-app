"""Treatment cost estimate: one treatment at one kind of hospital (see app/services/treatment_cost.py)."""

from dataclasses import asdict
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.routers.patients import get_profile
from app.routers.policies import active_policy
from app.security import get_current_user
from app.services import coverage
from app.services import treatment_cost as tc
from app.services.ml import registry

router = APIRouter(prefix="/api/cost", tags=["treatment cost estimate"])


class TreatmentEstimateRequest(BaseModel):
    treatment: str
    city_tier: Literal["metro", "tier2", "tier3"]
    hospital_type: Literal["government", "private", "multispeciality", "premium"]
    ward_days: Optional[int] = Field(None, ge=0, le=60)
    icu_days: int = Field(0, ge=0, le=30)
    room: Literal["general_ward", "semi_private", "private", "deluxe"] = "general_ward"
    emergency: bool = False
    conditions: list[str] = []
    age: Optional[int] = Field(None, ge=0, le=120)


@router.get("/treatments", summary="Treatments the estimate covers, with their package rates")
def treatments(_: User = Depends(get_current_user)):
    return {
        "treatments": [asdict(t) for t in tc.TREATMENTS],
        "conditions": [{"key": k, "label": v[0]} for k, v in tc.CONDITIONS.items()],
        "rooms": [{"key": k, "label": v} for k, v in tc.ROOM_LABEL.items()],
        "source": "AB PM-JAY Health Benefit Package 2022 (as published in the CMHIS Nagaland package list): "
                  "Tier-3 city rates, general ward, all inclusive except implants.",
    }


@router.post("/treatment", summary="Estimate one treatment's cost, and what the patient's policy would pay")
def estimate_treatment(body: TreatmentEstimateRequest, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    if body.treatment not in tc.BY_KEY:
        raise HTTPException(422, f"Unknown treatment '{body.treatment}'.")
    if registry.bill is None:
        raise HTTPException(503, "The bill analysis models are not loaded. Check /api/health.")

    age = body.age
    policy = None
    if user.role == "patient":
        age = age if age is not None else get_profile(db, user).age
        policy = active_policy(db, user.id)

    result = tc.estimate(body.treatment, body.city_tier, body.hospital_type, body.ward_days, body.icu_days,
                         body.room, body.emergency, tuple(body.conditions), age)

    # what the patient's own policy would pay, with Member 3's cost calculator (as for a real bill)
    insurance = None
    if policy is not None:
        bill = registry.bill
        lines = [bill.BillLineItem(d, c, a, is_covered=True) for d, c, a in tc.bill_lines(result)]
        cost = bill.CostCalculator(bill.InsurancePolicy(
            deductible=policy.deductible, co_insurance_pct=policy.co_insurance_pct, copay_flat=policy.copay_flat,
            category_caps={"room_rent": policy.room_rent_cap} if policy.room_rent_cap else {},
            overall_cap=coverage.left(db, policy),  # what is left of the yearly sum insured
        )).calculate(lines)
        # the calculator counts anything above the insurer's limit as co-insurance; report it separately
        co_insurance = (cost.covered_amount - cost.deductible_applied) * policy.co_insurance_pct / 100
        insurance = {
            "policy_number": policy.policy_number, "insurer": policy.insurer.name,
            "insurance_pays": round(cost.insurance_pays), "patient_pays": round(cost.patient_out_of_pocket),
            "deductible": round(cost.deductible_applied), "co_insurance": round(co_insurance),
            "sum_insured_shortfall": round(cost.co_insurance_patient_share - co_insurance),
            "copay": round(cost.copay), "room_cap_deduction": round(cost.category_cap_deductions),
            "sum_insured_left": coverage.left(db, policy),
        }
    return {**result, "insurance": insurance}
