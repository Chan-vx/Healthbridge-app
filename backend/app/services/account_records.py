"""
Clearing one account's records, so a tester can start again.

    delete  remove the account's records
    reset   remove them, then put back the account's records from the demo data

An account's records:
    patient   bills for the patient (from any hospital), their claims and payments, cost estimates
    hospital  bills at the hospital (its own and patients' copies), their claims and payments
    insurer   claims sent to the insurer

Profiles, logins and policies are kept. A reset also restores the patient's profile and policy terms.

The demo data is rebuilt by running app/seed.py into a throwaway in-memory database (the same real
pipeline as a fresh install), and the account's rows are copied from there. Rows are matched to
the live database by email (users), name (hospitals, insurers) and policy number.
"""

import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import create_engine, delete, inspect, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Bill, BillItem, Claim, CostEstimate, Hospital, Insurer, PatientProfile, Payment, Policy, User

ROLES = ("patient", "hospital", "insurer")
_lock = threading.Lock()
_demo: Optional[Session] = None


def demo_data() -> Session:
    """The demo data, built once per server process."""
    global _demo
    with _lock:
        if _demo is None:
            from app.seed import seed  # noqa: PLC0415  (seed imports the routers)

            engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
            Base.metadata.create_all(engine)
            session = sessionmaker(bind=engine, expire_on_commit=False)()
            seed(session)
            _demo = session
    return _demo


def _aware(value):
    """SQLite drops time zones; the demo data's times are UTC."""
    return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value


def _copy(obj, **override):
    """A new, unsaved row with the same column values."""
    data = {attr.key: _aware(getattr(obj, attr.key)) for attr in inspect(type(obj)).column_attrs if attr.key != "id"}
    data.update(override)
    return type(obj)(**data)


def _bills(db: Session, user: User):
    if user.role == "patient":
        return select(Bill).where(Bill.patient_id == user.id)
    if user.role == "hospital" and user.hospital is not None:
        return select(Bill).where(Bill.hospital_id == user.hospital.id)
    return None


def counts(db: Session, user: User) -> dict:
    if user.role == "insurer":
        return {"claims": len(db.scalars(select(Claim.id).where(Claim.insurer_id == user.insurer.id)).all())}
    ids = db.scalars(_bills(db, user).with_only_columns(Bill.id)).all()
    out = {"bills": len(ids),
           "claims": len(db.scalars(select(Claim.id).where(Claim.bill_id.in_(ids))).all()) if ids else 0,
           "payments": len(db.scalars(select(Payment.id).where(Payment.bill_id.in_(ids))).all()) if ids else 0}
    if user.role == "patient":
        out["cost_estimates"] = len(db.scalars(select(CostEstimate.id).where(CostEstimate.patient_id == user.id)).all())
    return out


def _delete(db: Session, user: User) -> dict:
    removed = counts(db, user)
    if user.role == "insurer":
        db.execute(delete(Claim).where(Claim.insurer_id == user.insurer.id))
        return removed
    ids = db.scalars(_bills(db, user).with_only_columns(Bill.id)).all()
    if ids:
        db.execute(delete(Payment).where(Payment.bill_id.in_(ids)))
        db.execute(delete(Claim).where(Claim.bill_id.in_(ids)))
        db.execute(delete(BillItem).where(BillItem.bill_id.in_(ids)))
        db.execute(delete(Bill).where(Bill.id.in_(ids)))
        db.execute(update(Bill).where(Bill.matched_bill_id.in_(ids)).values(matched_bill_id=None))
    if user.role == "patient":
        db.execute(delete(CostEstimate).where(CostEstimate.patient_id == user.id))
    return removed


class _Ids:
    """Maps demo-data ids to live ids."""

    def __init__(self, demo: Session, db: Session):
        live_users = {u.email: u.id for u in db.scalars(select(User))}
        live_hospitals = {h.name: h.id for h in db.scalars(select(Hospital))}
        live_insurers = {i.name: i.id for i in db.scalars(select(Insurer))}
        live_policies = {p.policy_number: p.id for p in db.scalars(select(Policy))}
        self.user = {u.id: live_users.get(u.email) for u in demo.scalars(select(User))}
        self.hospital = {h.id: live_hospitals.get(h.name) for h in demo.scalars(select(Hospital))}
        self.insurer = {i.id: live_insurers.get(i.name) for i in demo.scalars(select(Insurer))}
        self.policy = {p.id: live_policies.get(p.policy_number) for p in demo.scalars(select(Policy))}
        self.bill: dict[int, int] = {}


def _claim(c: Claim, ids: _Ids, bill_id: int) -> Claim:
    return _copy(c, claim_number=f"RESET-{uuid.uuid4().hex[:12]}", bill_id=bill_id, patient_id=ids.user[c.patient_id],
                 hospital_id=ids.hospital.get(c.hospital_id), insurer_id=ids.insurer[c.insurer_id],
                 policy_id=ids.policy.get(c.policy_id), submitted_by=ids.user[c.submitted_by])


def _restore(db: Session, user: User) -> dict:
    demo = demo_data()
    ids = _Ids(demo, db)
    me = demo.scalar(select(User).where(User.email == user.email))
    restored = {"bills": 0, "claims": 0, "payments": 0, "cost_estimates": 0, "skipped_claims": 0}
    if me is None:  # an account that is not part of the demo data: nothing to put back
        return restored
    new_claims = []

    if user.role == "insurer":
        # claims go back onto the live bills they were made for, when those bills still exist unclaimed
        for c in demo.scalars(select(Claim).where(Claim.insurer_id == me.insurer.id).order_by(Claim.id)):
            b = demo.get(Bill, c.bill_id)
            live = db.scalar(select(Bill).where(
                Bill.patient_id == ids.user[b.patient_id], Bill.hospital_id == ids.hospital.get(b.hospital_id),
                Bill.total_billed == b.total_billed, Bill.bill_number.is_(None) if b.bill_number is None else Bill.bill_number == b.bill_number))
            taken = live is not None and db.scalar(select(Claim.id).where(Claim.bill_id == live.id, Claim.status != "rejected"))
            if live is None or taken:
                restored["skipped_claims"] += 1
                continue
            new_claims.append(_claim(c, ids, live.id))
    else:
        query = (select(Bill).where(Bill.patient_id == me.id) if user.role == "patient"
                 else select(Bill).where(Bill.hospital_id == me.hospital.id))
        demo_bills = demo.scalars(query.order_by(Bill.id)).all()
        for b in demo_bills:
            new = _copy(b, patient_id=ids.user[b.patient_id], hospital_id=ids.hospital.get(b.hospital_id),
                        policy_id=ids.policy.get(b.policy_id), uploaded_by=ids.user[b.uploaded_by], matched_bill_id=None)
            db.add(new)
            db.flush()
            ids.bill[b.id] = new.id
            for item in b.items:
                db.add(_copy(item, bill_id=new.id))
        for b in demo_bills:
            if b.matched_bill_id in ids.bill:
                db.get(Bill, ids.bill[b.id]).matched_bill_id = ids.bill[b.matched_bill_id]
            for c in demo.scalars(select(Claim).where(Claim.bill_id == b.id)):
                new_claims.append(_claim(c, ids, ids.bill[b.id]))
            for p in demo.scalars(select(Payment).where(Payment.bill_id == b.id)):
                db.add(_copy(p, bill_id=ids.bill[b.id], patient_id=ids.user[p.patient_id]))
                restored["payments"] += 1
        restored["bills"] = len(demo_bills)

    if user.role == "patient":
        for e in demo.scalars(select(CostEstimate).where(CostEstimate.patient_id == me.id)):
            db.add(_copy(e, patient_id=user.id))
            restored["cost_estimates"] += 1
        profile = demo.scalar(select(PatientProfile).where(PatientProfile.user_id == me.id))
        live_profile = db.scalar(select(PatientProfile).where(PatientProfile.user_id == user.id))
        if profile and live_profile:
            for attr in inspect(PatientProfile).column_attrs:
                if attr.key not in ("id", "user_id"):
                    setattr(live_profile, attr.key, getattr(profile, attr.key))
        for p in demo.scalars(select(Policy).where(Policy.patient_id == me.id)):
            live = db.get(Policy, ids.policy[p.id]) if ids.policy.get(p.id) else None
            if live is None:
                db.add(_copy(p, patient_id=user.id, insurer_id=ids.insurer[p.insurer_id]))
            else:
                for key in ("deductible", "co_insurance_pct", "copay_flat", "room_rent_cap", "sum_insured", "active", "created_at"):
                    setattr(live, key, _aware(getattr(p, key)))

    for c in new_claims:
        db.add(c)
        db.flush()
        c.claim_number = f"CLM-{c.submitted_at.year}-{c.id:05d}"
    restored["claims"] = len(new_claims)
    return restored


def clear(db: Session, user: User, action: str) -> dict:
    """Delete the account's records; for 'reset', put the demo data back. One transaction."""
    if action == "reset":
        demo_data()  # build it before deleting anything: if it fails, nothing is lost
    removed = _delete(db, user)
    db.flush()
    restored = _restore(db, user) if action == "reset" else None
    db.commit()
    return {"action": action, "removed": removed, "restored": restored}
