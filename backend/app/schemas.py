"""Pydantic request/response models (validation for every endpoint)."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

SelfServiceRole = Literal["patient", "hospital", "insurer"]
CityTier = Literal["metro", "tier2", "tier3"]
HospitalType = Literal["government", "private", "multispeciality", "premium"]
Region = Literal["northeast", "northwest", "southeast", "southwest"]
Specialty = Literal["Cardiology", "General Practice", "Neurology", "Orthopedics", "Pediatrics"]
ClaimType = Literal["Emergency", "Inpatient", "Outpatient", "Routine"]
SubmissionMethod = Literal["Online", "Paper", "Phone"]
Marital = Literal["Single", "Married", "Divorced", "Widowed"]
Employment = Literal["Employed", "Unemployed", "Retired", "Student"]
Category = Literal["room_rent", "procedure", "medicine", "diagnostic", "nursing", "consultation", "cosmetic", "other"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=2, max_length=255)
    role: SelfServiceRole
    organization_name: Optional[str] = Field(default=None, description="Hospital or insurer name")
    city: Optional[str] = None
    city_tier: CityTier = "tier2"
    hospital_type: HospitalType = "private"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    role: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------------------------------------------------------------- profiles


class PatientProfileIn(BaseModel):
    age: int = Field(ge=18, le=100)
    sex: Literal["male", "female"]
    bmi: float = Field(ge=10, le=70)
    children: int = Field(ge=0, le=10)
    smoker: Literal["yes", "no"]
    region: Region
    marital_status: Marital = "Single"
    employment_status: Employment = "Employed"
    monthly_income: float = Field(ge=0)
    existing_monthly_debt: float = Field(ge=0, default=0)
    has_credit_card: bool = True


class PatientProfileOut(PatientProfileIn, ORMModel):
    id: int
    user_id: int


class HospitalOut(ORMModel):
    id: int
    name: str
    city: str
    city_tier: str
    hospital_type: str


class InsurerOut(ORMModel):
    id: int
    name: str


class PersonOut(BaseModel):
    id: int
    full_name: str
    email: str


# ---------------------------------------------------------------- cost


class CostEstimateRequest(BaseModel):
    """Leave empty to use the saved profile."""

    age: Optional[int] = Field(default=None, ge=18, le=100)
    sex: Optional[Literal["male", "female"]] = None
    bmi: Optional[float] = Field(default=None, ge=10, le=70)
    children: Optional[int] = Field(default=None, ge=0, le=10)
    smoker: Optional[Literal["yes", "no"]] = None
    region: Optional[Region] = None


class CostEstimateOut(ORMModel):
    id: int
    inputs: dict
    predicted_usd: float
    predicted_inr: float
    shap: list
    created_at: datetime


# ---------------------------------------------------------------- policies


class PolicyIn(BaseModel):
    patient_email: EmailStr
    deductible: float = Field(ge=0, default=5000)
    co_insurance_pct: float = Field(ge=0, le=100, default=20)
    copay_flat: float = Field(ge=0, default=500)
    room_rent_cap: Optional[float] = Field(default=20000, ge=0)
    sum_insured: Optional[float] = Field(default=500000, ge=0)


class PolicyOut(ORMModel):
    id: int
    policy_number: str
    patient_id: int
    insurer_id: int
    deductible: float
    co_insurance_pct: float
    copay_flat: float
    room_rent_cap: Optional[float]
    sum_insured: Optional[float]
    active: bool
    created_at: datetime
    patient_name: Optional[str] = None
    insurer_name: Optional[str] = None


# ---------------------------------------------------------------- bills


class ManualItem(BaseModel):
    description: str = Field(min_length=1, max_length=255)
    amount: float = Field(gt=0)
    quantity: Optional[int] = Field(default=None, ge=1, le=365)
    category: Optional[Category] = None


class ManualBillRequest(BaseModel):
    patient_id: Optional[int] = Field(default=None, description="Required when a hospital uploads")
    hospital_id: Optional[int] = Field(default=None, description="Required when a patient uploads")
    bill_number: Optional[str] = None
    admission_date: Optional[str] = None
    discharge_date: Optional[str] = None
    items: list[ManualItem] = Field(min_length=1)


class TextBillRequest(BaseModel):
    patient_id: Optional[int] = None
    hospital_id: Optional[int] = None
    raw_text: str = Field(min_length=10)


class BillItemOut(ORMModel):
    id: int
    description: str
    category: str
    amount: float
    quantity: int
    is_covered: bool
    fair_price: Optional[float]
    overcharge_pct: Optional[float]
    ml_anomaly: bool
    severity: str
    duplicate_of: Optional[str]
    duplicate_similarity: Optional[float]


class BillSummaryOut(ORMModel):
    id: int
    patient_id: int
    hospital_id: Optional[int]
    source: str
    hospital_name: Optional[str]
    bill_number: Optional[str]
    total_billed: float
    insurance_pays: float
    patient_out_of_pocket: float
    flagged_amount: float
    duplicate_count: int
    high_risk_count: int
    total_mismatch: bool
    payment_status: str
    created_at: datetime
    patient_name: Optional[str] = None
    claim_status: Optional[str] = None


class BillDetailOut(BillSummaryOut):
    admission_date: Optional[str]
    discharge_date: Optional[str]
    stated_total: Optional[float]
    city_tier: str
    hospital_type: str
    raw_text: Optional[str]
    cost_breakdown: dict
    emi: dict
    recommendations: list
    items: list[BillItemOut]
    policy_id: Optional[int]
    claim_id: Optional[int] = None
    payment: Optional[dict] = None


class EMIRequest(BaseModel):
    annual_rate: float = Field(ge=0, le=60, default=13.5)
    months: int = Field(ge=1, le=120, default=12)


class PaymentRequest(BaseModel):
    plan: Literal["full", "emi"]
    annual_rate: float = Field(ge=0, le=60, default=13.5)
    months: int = Field(ge=1, le=120, default=12)


# ---------------------------------------------------------------- claims


class ClaimRequest(BaseModel):
    bill_id: int
    claim_type: ClaimType
    provider_specialty: Specialty
    submission_method: SubmissionMethod = "Online"


class ClaimDecision(BaseModel):
    action: Literal["approve", "reject", "settle"]
    approved_amount: Optional[float] = Field(default=None, ge=0)
    note: Optional[str] = Field(default=None, max_length=1000)


class ClaimOut(ORMModel):
    id: int
    claim_number: str
    bill_id: Optional[int]
    patient_id: int
    hospital_id: Optional[int]
    insurer_id: int
    policy_id: Optional[int]
    claim_amount: float
    claim_type: str
    provider_specialty: str
    submission_method: str
    provider_location: str
    fraud_probability: float
    anomaly_score: float
    hybrid_risk_score: float
    fraud_prediction: int
    risk_level: str
    recommendation: str
    top_factors: list
    model_inputs: dict
    status: str
    approved_amount: Optional[float]
    decision_note: Optional[str]
    submitted_at: datetime
    decided_at: Optional[datetime]
    patient_name: Optional[str] = None
    hospital_name: Optional[str] = None
    insurer_name: Optional[str] = None
    advice: Optional[dict] = None  # Claim Decision Engine recommendation
