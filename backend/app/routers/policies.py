import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Policy, User
from app.schemas import PolicyIn, PolicyOut
from app.security import get_current_user, require_roles

router = APIRouter(prefix="/api/policies", tags=["policies"])


def policy_out(p: Policy) -> PolicyOut:
    out = PolicyOut.model_validate(p)
    out.patient_name = p.patient.full_name
    out.insurer_name = p.insurer.name
    return out


def active_policy(db: Session, patient_id: int) -> Policy | None:
    return db.scalar(select(Policy).where(Policy.patient_id == patient_id, Policy.active.is_(True))
                     .order_by(Policy.created_at.desc()))


@router.post("", response_model=PolicyOut, status_code=201)
def create_policy(body: PolicyIn, user: User = Depends(require_roles("insurer")), db: Session = Depends(get_db)):
    patient = db.scalar(select(User).where(User.email == body.patient_email.lower(), User.role == "patient"))
    if patient is None:
        raise HTTPException(404, "No patient account uses that email.")
    # one active policy per patient keeps the bill calculation unambiguous
    for old in db.scalars(select(Policy).where(Policy.patient_id == patient.id, Policy.active.is_(True))):
        old.active = False
    policy = Policy(
        policy_number=f"POL-{secrets.token_hex(3).upper()}", patient_id=patient.id, insurer_id=user.insurer.id,
        **body.model_dump(exclude={"patient_email"}),
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy_out(policy)


@router.get("", response_model=list[PolicyOut])
def list_policies(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Policy).order_by(Policy.created_at.desc())
    if user.role == "patient":
        query = query.where(Policy.patient_id == user.id)
    elif user.role == "insurer":
        query = query.where(Policy.insurer_id == user.insurer.id)
    elif user.role == "hospital":
        raise HTTPException(403, "Hospitals cannot view insurance policies.")
    return [policy_out(p) for p in db.scalars(query)]
