"""
Demo data for reviews. Every bill and claim is produced by the real pipeline
(Member 3's analyzer, Member 2's fraud engine); only the dates are spread over
recent months so the dashboards have trends to show.

Run manually:  python -m app.seed      (or set SEED_DEMO=true)
All demo accounts use the password  Demo@1234
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bill, Claim, CostEstimate, Hospital, Insurer, PatientProfile, Payment, Policy, User
from app.routers.bills import manual_bill, sample_bill
from app.routers.claims import decide_claim, submit_claim
from app.routers.bills import pay_bill
from app.schemas import ClaimDecision, ClaimRequest, ManualBillRequest, ManualItem, PaymentRequest
from app.security import hash_password
from app.services.ml import registry

PASSWORD = "Demo@1234"


def _user(db: Session, email: str, name: str, role: str) -> User:
    user = User(email=email, password_hash=hash_password(PASSWORD), full_name=name, role=role)
    db.add(user)
    db.flush()
    return user


def _items(*rows) -> list[ManualItem]:
    return [ManualItem(description=d, amount=a) for d, a in rows]


def seed(db: Session) -> bool:
    if db.scalar(select(User).limit(1)) is not None:
        return False
    if registry.bill is None or registry.fraud is None or registry.cost is None:
        registry.load()

    _user(db, "admin@healthbridge.in", "Platform Admin", "admin")
    _user(db, "finance@healthbridge.in", "Anita Rao (Finance)", "finance")

    h1u = _user(db, "citycare@hospital.in", "City Care Billing Desk", "hospital")
    h1 = Hospital(user_id=h1u.id, name="City Care Multispeciality Hospital", city="Chennai",
                  city_tier="metro", hospital_type="multispeciality")
    h2u = _user(db, "sunrise@hospital.in", "Sunrise Billing Desk", "hospital")
    h2 = Hospital(user_id=h2u.id, name="Sunrise General Hospital", city="Coimbatore",
                  city_tier="tier2", hospital_type="private")
    iu = _user(db, "claims@suraksha.in", "Suraksha Claims Team", "insurer")
    ins = Insurer(user_id=iu.id, name="Suraksha Health Insurance")
    db.add_all([h1, h2, ins])
    db.flush()

    patients = [
        ("ramesh@patient.in", "Ramesh Kumar", dict(age=45, sex="male", bmi=31.2, children=2, smoker="no",
                                                  region="southeast", marital_status="Married",
                                                  employment_status="Employed", monthly_income=22000,
                                                  existing_monthly_debt=3000)),
        ("priya@patient.in", "Priya Sharma", dict(age=32, sex="female", bmi=23.4, children=1, smoker="no",
                                                  region="northwest", marital_status="Married",
                                                  employment_status="Employed", monthly_income=85000,
                                                  existing_monthly_debt=12000)),
        ("arjun@patient.in", "Arjun Reddy", dict(age=58, sex="male", bmi=34.8, children=3, smoker="yes",
                                                 region="southwest", marital_status="Married",
                                                 employment_status="Retired", monthly_income=18000,
                                                 existing_monthly_debt=0)),
        ("meena@patient.in", "Meena Iyer", dict(age=27, sex="female", bmi=21.0, children=0, smoker="no",
                                                region="northeast", marital_status="Single",
                                                employment_status="Student", monthly_income=0,
                                                existing_monthly_debt=0, has_credit_card=False)),
    ]
    pu = {}
    for email, name, profile in patients:
        user = _user(db, email, name, "patient")
        db.add(PatientProfile(user_id=user.id, **profile))
        pu[email] = user
    db.flush()

    policy_terms = {
        "ramesh@patient.in": dict(deductible=5000, co_insurance_pct=20, copay_flat=500, room_rent_cap=20000,
                                  sum_insured=150000),
        "priya@patient.in": dict(deductible=10000, co_insurance_pct=10, copay_flat=0, room_rent_cap=None,
                                 sum_insured=500000),
        "arjun@patient.in": dict(deductible=0, co_insurance_pct=10, copay_flat=1000, room_rent_cap=15000,
                                 sum_insured=1000000),
    }
    for n, (email, terms) in enumerate(policy_terms.items(), start=1):
        db.add(Policy(policy_number=f"POL-DEMO{n:02d}", patient_id=pu[email].id, insurer_id=ins.id, **terms))
    db.commit()

    now = datetime.now(timezone.utc)
    ago = lambda days: now - timedelta(days=days)  # noqa: E731

    for email in ("ramesh@patient.in", "priya@patient.in", "arjun@patient.in"):
        p = db.scalar(select(PatientProfile).where(PatientProfile.user_id == pu[email].id))
        r = registry.cost.predict(p.age, p.sex, p.bmi, p.children, p.smoker, p.region)
        db.add(CostEstimate(patient_id=pu[email].id, predicted_usd=r["predicted_usd"],
                            predicted_inr=r["predicted_inr"], shap=r["shap"],
                            inputs=dict(age=p.age, sex=p.sex, bmi=p.bmi, children=p.children, smoker=p.smoker,
                                        region=p.region)))
    db.commit()

    # Amounts sit near Member 3's synthetic fair prices (City Care = metro/multispeciality,
    # Sunrise = tier2/private) so most items read "normal"; two bills are inflated on purpose:
    # the emergency CT scan (rejected claim) and the cardiac bill (HIGH fraud risk, still open).
    # (patient, hospital user, items or "sample", claim settings, decision, payment, days ago)
    scenarios = [
        ("ramesh@patient.in", h1u, "sample", ("Inpatient", "General Practice"), "approve", ("emi", 12), 150),
        ("priya@patient.in", h1u, _items(("Consultation - Cardiologist", 1050), ("Diagnostic - ECG", 3300),
                                          ("Echo Cardiogram Scan", 3500), ("Medicines - Atorvastatin 10mg", 260)),
         None, None, ("full", 1), 120),
        ("meena@patient.in", h2u, _items(("Consultation - Physician", 600), ("Blood Test - CBC", 2100),
                                          ("Tablet Paracetamol 500mg", 150)),
         None, None, None, 105),
        ("arjun@patient.in", h2u, _items(("Room Rent (6 days)", 18500), ("Surgery - Knee Arthroscopy", 38000),
                                          ("Nursing Charges (6 days)", 7100), ("MRI Scan Knee", 2150),
                                          ("Physiotherapy consultation", 620), ("Injection Antibiotic 1g", 160)),
         ("Inpatient", "Orthopedics"), "approve", None, 90),
        ("priya@patient.in", h2u, _items(("Emergency Consultation", 650), ("CT Scan Head", 9500),
                                          ("Blood Test - CBC", 2050), ("Blood Test CBC", 2050),
                                          ("Injection Ondansetron", 160), ("Observation Room Rent (1 day)", 3100)),
         ("Emergency", "Neurology"), "reject", None, 60),
        ("ramesh@patient.in", h1u, _items(("Consultation - Neurologist", 1000), ("MRI Scan Brain", 3500)),
         None, None, ("full", 1), 45),
        ("arjun@patient.in", h1u, _items(("Room Rent (8 days)", 64000), ("Surgery - Coronary Bypass (CABG)", 540000),
                                          ("Anaesthetist Fee", 60000), ("ICU Nursing Charges (8 days)", 48000),
                                          ("Diagnostic - Angiography", 38000), ("Medicines - Heparin injection", 7800),
                                          ("Cardiology consultation", 5000)),
         ("Inpatient", "Cardiology"), None, None, 30),
        ("arjun@patient.in", h2u, _items(("Consultation - Physician", 650), ("X-Ray Chest", 2100),
                                          ("Diagnostic - ECG", 1900), ("Tablet Azithromycin 500mg", 160),
                                          ("Nebuliser medicine - Salbutamol", 170)),
         ("Outpatient", "General Practice"), "settle", None, 12),
        ("priya@patient.in", h1u, _items(("Room Rent (3 days)", 15500), ("Surgery - Laparoscopic Cholecystectomy", 62000),
                                          ("Anaesthetist Fee", 12000), ("Ultrasound Abdomen Scan", 3300),
                                          ("Nursing Charges (3 days)", 6000), ("Cosmetic scar gel (non-medical)", 2200)),
         ("Inpatient", "General Practice"), None, None, 4),
    ]

    for email, hosp_user, items, claim_cfg, decision, payment, days in scenarios:
        patient = pu[email]
        if items == "sample":
            bill_out = sample_bill(patient_id=patient.id, hospital_id=None, user=hosp_user, db=db)
        else:
            bill_out = manual_bill(ManualBillRequest(patient_id=patient.id, items=items), user=hosp_user, db=db)
        bill = db.get(Bill, bill_out.id)
        bill.created_at = ago(days)

        if claim_cfg and bill.insurance_pays > 0:
            claim_type, specialty = claim_cfg
            c = submit_claim(ClaimRequest(bill_id=bill.id, claim_type=claim_type, provider_specialty=specialty),
                             user=hosp_user, db=db)
            claim = db.get(Claim, c.id)
            claim.submitted_at = ago(days - 1)
            if decision in ("approve", "settle"):
                decide_claim(claim.id, ClaimDecision(action="approve", note="Documents verified."), user=iu, db=db)
            if decision == "settle":
                decide_claim(claim.id, ClaimDecision(action="settle"), user=iu, db=db)
            if decision == "reject":
                decide_claim(claim.id, ClaimDecision(
                    action="reject", note="Duplicate CBC line and CT charge far above tariff; resubmit corrected bill."),
                    user=iu, db=db)
            if decision:
                claim.decided_at = ago(max(days - 5, 1))

        if payment and bill.patient_out_of_pocket > 0:
            plan, months = payment
            pay_bill(bill.id, PaymentRequest(plan=plan, months=months), user=patient, db=db)
            for pay in db.scalars(select(Payment).where(Payment.bill_id == bill.id)):
                pay.created_at = ago(max(days - 2, 1))
        db.commit()
    return True


if __name__ == "__main__":
    from app.database import Base, SessionLocal, engine

    Base.metadata.create_all(engine)
    registry.load()
    with SessionLocal() as session:
        print("Seeded demo data." if seed(session) else "Database already has users; seed skipped.")
