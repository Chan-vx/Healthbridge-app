"""PostgreSQL schema (SQLAlchemy ORM)."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

ROLES = ("patient", "hospital", "insurer", "finance", "admin")
CLAIM_STATUSES = ("submitted", "approved", "rejected", "settled")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    patient_profile: Mapped[Optional["PatientProfile"]] = relationship(back_populates="user", uselist=False)
    hospital: Mapped[Optional["Hospital"]] = relationship(back_populates="user", uselist=False)
    insurer: Mapped[Optional["Insurer"]] = relationship(back_populates="user", uselist=False)


class PatientProfile(Base):
    """Fields used by Member 1 (cost), Member 2 (fraud) and Member 3 (recommendations)."""

    __tablename__ = "patient_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    age: Mapped[int] = mapped_column(Integer, default=30)
    sex: Mapped[str] = mapped_column(String(10), default="male")
    bmi: Mapped[float] = mapped_column(Float, default=25.0)
    children: Mapped[int] = mapped_column(Integer, default=0)
    smoker: Mapped[str] = mapped_column(String(5), default="no")
    region: Mapped[str] = mapped_column(String(20), default="southeast")
    marital_status: Mapped[str] = mapped_column(String(20), default="Single")
    employment_status: Mapped[str] = mapped_column(String(20), default="Employed")
    monthly_income: Mapped[float] = mapped_column(Float, default=0.0)
    existing_monthly_debt: Mapped[float] = mapped_column(Float, default=0.0)
    has_credit_card: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="patient_profile")


class Hospital(Base):
    __tablename__ = "hospitals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(100), default="")
    city_tier: Mapped[str] = mapped_column(String(10), default="tier2")
    hospital_type: Mapped[str] = mapped_column(String(20), default="private")

    user: Mapped[User] = relationship(back_populates="hospital")


class Insurer(Base):
    __tablename__ = "insurers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(255))

    user: Mapped[User] = relationship(back_populates="insurer")


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_number: Mapped[str] = mapped_column(String(50), unique=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    insurer_id: Mapped[int] = mapped_column(ForeignKey("insurers.id"), index=True)
    deductible: Mapped[float] = mapped_column(Float, default=0.0)
    co_insurance_pct: Mapped[float] = mapped_column(Float, default=0.0)
    copay_flat: Mapped[float] = mapped_column(Float, default=0.0)
    room_rent_cap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sum_insured: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    patient: Mapped[User] = relationship()
    insurer: Mapped[Insurer] = relationship()


class CostEstimate(Base):
    __tablename__ = "cost_estimates"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    inputs: Mapped[dict] = mapped_column(JSON)
    predicted_usd: Mapped[float] = mapped_column(Float)
    predicted_inr: Mapped[float] = mapped_column(Float)
    shap: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Bill(Base):
    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    hospital_id: Mapped[Optional[int]] = mapped_column(ForeignKey("hospitals.id"), nullable=True, index=True)
    policy_id: Mapped[Optional[int]] = mapped_column(ForeignKey("policies.id"), nullable=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(10), default="manual")  # "ocr" | "manual"
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    hospital_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bill_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    admission_date: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    discharge_date: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    city_tier: Mapped[str] = mapped_column(String(10), default="tier2")
    hospital_type: Mapped[str] = mapped_column(String(20), default="private")

    stated_total: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_billed: Mapped[float] = mapped_column(Float, default=0.0)
    total_mismatch: Mapped[bool] = mapped_column(Boolean, default=False)
    insurance_pays: Mapped[float] = mapped_column(Float, default=0.0)
    patient_out_of_pocket: Mapped[float] = mapped_column(Float, default=0.0)
    flagged_amount: Mapped[float] = mapped_column(Float, default=0.0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    high_risk_count: Mapped[int] = mapped_column(Integer, default=0)

    cost_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    emi: Mapped[dict] = mapped_column(JSON, default=dict)
    recommendations: Mapped[list] = mapped_column(JSON, default=list)
    payment_status: Mapped[str] = mapped_column(String(20), default="unpaid")  # unpaid | paid | on_emi
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items: Mapped[list["BillItem"]] = relationship(back_populates="bill", cascade="all, delete-orphan")
    patient: Mapped[User] = relationship(foreign_keys=[patient_id])
    hospital: Mapped[Optional[Hospital]] = relationship()


class BillItem(Base):
    __tablename__ = "bill_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("bills.id"), index=True)
    description: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(30))
    amount: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    is_covered: Mapped[bool] = mapped_column(Boolean, default=True)
    fair_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    overcharge_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ml_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    severity: Mapped[str] = mapped_column(String(20), default="normal")  # normal | review | high_risk
    duplicate_of: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    duplicate_similarity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    bill: Mapped[Bill] = relationship(back_populates="items")


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_number: Mapped[str] = mapped_column(String(50), unique=True)
    bill_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bills.id"), nullable=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    hospital_id: Mapped[Optional[int]] = mapped_column(ForeignKey("hospitals.id"), nullable=True, index=True)
    insurer_id: Mapped[int] = mapped_column(ForeignKey("insurers.id"), index=True)
    policy_id: Mapped[Optional[int]] = mapped_column(ForeignKey("policies.id"), nullable=True)
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"))

    claim_amount: Mapped[float] = mapped_column(Float)
    claim_type: Mapped[str] = mapped_column(String(20))
    provider_specialty: Mapped[str] = mapped_column(String(30))
    submission_method: Mapped[str] = mapped_column(String(10), default="Online")
    provider_location: Mapped[str] = mapped_column(String(100), default="")

    # Member 2's fraud engine output, stored at submission time
    fraud_probability: Mapped[float] = mapped_column(Float, default=0.0)
    anomaly_score: Mapped[float] = mapped_column(Float, default=0.0)
    hybrid_risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    fraud_prediction: Mapped[int] = mapped_column(Integer, default=0)
    risk_level: Mapped[str] = mapped_column(String(10), default="LOW", index=True)
    recommendation: Mapped[str] = mapped_column(String(50), default="")
    top_factors: Mapped[list] = mapped_column(JSON, default=list)
    model_inputs: Mapped[dict] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(String(20), default="submitted", index=True)
    approved_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    decision_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    patient: Mapped[User] = relationship(foreign_keys=[patient_id])
    hospital: Mapped[Optional[Hospital]] = relationship()
    insurer: Mapped[Insurer] = relationship()
    bill: Mapped[Optional[Bill]] = relationship()
    policy: Mapped[Optional[Policy]] = relationship()


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("bills.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan: Mapped[str] = mapped_column(String(20))  # full | emi
    principal: Mapped[float] = mapped_column(Float)
    annual_rate: Mapped[float] = mapped_column(Float, default=0.0)
    tenure_months: Mapped[int] = mapped_column(Integer, default=1)
    monthly_emi: Mapped[float] = mapped_column(Float)
    total_payment: Mapped[float] = mapped_column(Float)
    schedule: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
