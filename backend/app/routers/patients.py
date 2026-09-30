"""Patient profile, directory lookups, and Member 1's cost prediction."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CostEstimate, Hospital, Insurer, PatientProfile, User
from app.schemas import (
    CostEstimateOut,
    CostEstimateRequest,
    HospitalOut,
    InsurerOut,
    PatientProfileIn,
    PatientProfileOut,
    PersonOut,
)
from app.security import get_current_user, require_roles
from app.services.ml import registry

router = APIRouter(prefix="/api", tags=["patients"])


def get_profile(db: Session, user: User) -> PatientProfile:
    profile = db.scalar(select(PatientProfile).where(PatientProfile.user_id == user.id))
    if profile is None:
        profile = PatientProfile(user_id=user.id)
        db.add(profile)
        db.flush()
    return profile


@router.get("/patients/me/profile", response_model=PatientProfileOut)
def read_profile(user: User = Depends(require_roles("patient")), db: Session = Depends(get_db)):
    profile = get_profile(db, user)
    db.commit()
    return profile


@router.put("/patients/me/profile", response_model=PatientProfileOut)
def update_profile(body: PatientProfileIn, user: User = Depends(require_roles("patient")),
                   db: Session = Depends(get_db)):
    profile = get_profile(db, user)
    for key, value in body.model_dump().items():
        setattr(profile, key, value)
    db.commit()
    return profile


@router.get("/patients", response_model=list[PersonOut])
def list_patients(_: User = Depends(require_roles("hospital", "insurer", "finance", "admin")),
                  db: Session = Depends(get_db)):
    users = db.scalars(select(User).where(User.role == "patient").order_by(User.full_name))
    return [PersonOut(id=u.id, full_name=u.full_name, email=u.email) for u in users]


@router.get("/hospitals", response_model=list[HospitalOut])
def list_hospitals(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Hospital).order_by(Hospital.name)).all()


@router.get("/insurers", response_model=list[InsurerOut])
def list_insurers(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Insurer).order_by(Insurer.name)).all()


@router.post("/cost/estimate", response_model=CostEstimateOut, tags=["member 1 · cost prediction"])
def estimate_cost(body: CostEstimateRequest, user: User = Depends(require_roles("patient")),
                  db: Session = Depends(get_db)):
    if registry.cost is None:
        raise HTTPException(503, "The cost prediction model is not loaded. Check /api/health.")
    profile = get_profile(db, user)
    inputs = {
        field: getattr(body, field) if getattr(body, field) is not None else getattr(profile, field)
        for field in ("age", "sex", "bmi", "children", "smoker", "region")
    }
    result = registry.cost.predict(**inputs)
    estimate = CostEstimate(patient_id=user.id, inputs=inputs, predicted_usd=result["predicted_usd"],
                            predicted_inr=result["predicted_inr"], shap=result["shap"])
    db.add(estimate)
    db.commit()
    return estimate


@router.get("/cost/estimates", response_model=list[CostEstimateOut], tags=["member 1 · cost prediction"])
def list_estimates(user: User = Depends(require_roles("patient")), db: Session = Depends(get_db)):
    return db.scalars(select(CostEstimate).where(CostEstimate.patient_id == user.id)
                      .order_by(CostEstimate.created_at.desc()).limit(20)).all()
