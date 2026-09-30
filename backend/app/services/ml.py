"""
Adapters around the three team modules. The backend never re-implements a
model: each adapter imports the member's own code from ml_modules/ and only
translates between platform records (INR, database fields) and model inputs.

    Member 1  ml_modules/cost/api/shap_explanation.py   -> CostModel
    Member 2  ml_modules/fraud/src/api.py                -> FraudModel
    Member 3  ml_modules/bill/bill_app/*                 -> BillAnalyzer
"""

import importlib.util
import re
import shutil
import sys
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import ML_DIR, settings

BILL_DIR = ML_DIR / "bill"
if str(BILL_DIR) not in sys.path:
    sys.path.insert(0, str(BILL_DIR))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class OCRUnavailableError(RuntimeError):
    pass


# ---------------------------------------------------------------- Member 1


class CostModel:
    """Gradient Boosting cost predictor + SHAP (trained on US data, USD)."""

    name = "Cost prediction (Gradient Boosting + SHAP)"

    def __init__(self):
        self._module = _load_module("hb_member1_shap", ML_DIR / "cost" / "api" / "shap_explanation.py")

    def predict(self, age: int, sex: str, bmi: float, children: int, smoker: str, region: str) -> dict:
        patient = {"age": age, "sex": sex, "bmi": bmi, "children": children, "smoker": smoker, "region": region}
        result = self._module.explain_prediction(patient)
        predicted_usd = float(result["predicted_expenses"])
        contributions = result["feature_contributions"]
        base_usd = predicted_usd - sum(c["shap_value"] for c in contributions)
        rate = settings.usd_to_inr
        return {
            "predicted_usd": round(predicted_usd, 2),
            "predicted_inr": round(predicted_usd * rate, 2),
            "base_value_usd": round(base_usd, 2),
            "usd_to_inr": rate,
            "shap": [
                {
                    "feature": c["feature"],
                    "value": patient.get(c["feature"]),
                    "shap_usd": c["shap_value"],
                    "shap_inr": round(c["shap_value"] * rate, 2),
                }
                for c in contributions
            ],
        }


# ---------------------------------------------------------------- Member 2


class FraudModel:
    """XGBoost + Isolation Forest hybrid risk engine with SHAP (Member 2's predict())."""

    name = "Fraud risk (XGBoost + Isolation Forest + SHAP)"

    SPECIALTIES = ["Cardiology", "General Practice", "Neurology", "Orthopedics", "Pediatrics"]
    CLAIM_TYPES = ["Emergency", "Inpatient", "Outpatient", "Routine"]
    SUBMISSION_METHODS = ["Online", "Paper", "Phone"]
    MARITAL = ["Single", "Married", "Divorced", "Widowed"]
    EMPLOYMENT = ["Employed", "Unemployed", "Retired", "Student"]

    def __init__(self):
        self._module = _load_module("hb_member2_api", ML_DIR / "fraud" / "src" / "api.py")
        self.threshold = float(self._module.THRESHOLD)

    def score(
        self,
        claim_amount_inr: float,
        patient_age: int,
        patient_sex: str,
        annual_income_inr: float,
        marital_status: str,
        employment_status: str,
        provider_specialty: str,
        provider_location: str,
        claim_type: str,
        submission_method: str,
        claim_date: datetime,
    ) -> dict:
        rate = settings.usd_to_inr
        inputs = {
            "ClaimAmount": round(max(claim_amount_inr / rate, 0.01), 2),
            "PatientAge": int(patient_age),
            "PatientGender": "F" if patient_sex.lower().startswith("f") else "M",
            "ProviderSpecialty": provider_specialty,
            "PatientIncome": round(max(annual_income_inr / rate, 0.0), 2),
            "PatientMaritalStatus": marital_status,
            "PatientEmploymentStatus": employment_status,
            "ProviderLocation": provider_location or "Unknown",
            "ClaimType": claim_type,
            "ClaimSubmissionMethod": submission_method,
            "ClaimYear": claim_date.year,
            "ClaimMonth": claim_date.month,
            "ClaimDayOfWeek": claim_date.weekday(),
        }
        request = self._module.ClaimRequest(**inputs)
        result = self._module.predict(request)
        return {**result, "model_inputs": inputs}


# ---------------------------------------------------------------- Member 3


class BillAnalyzer:
    """OCR -> parse -> duplicate + ML overcharge detection -> cost split -> EMI -> recommendations."""

    name = "Bill analyzer (OCR + RandomForest fair price + Isolation Forest)"

    DAY_BASED = {"room_rent", "nursing"}
    DATE_FORMATS = ("%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %b %Y")

    def __init__(self):
        from bill_app.calculators.cost_calculator import BillLineItem, CostCalculator, InsurancePolicy
        from bill_app.calculators.emi_calculator import EMICalculator
        from bill_app.detection.anomaly_detector import AnomalyDetector
        from bill_app.parsing.bill_parser import BillParser, categorize, is_non_covered
        from bill_app.recommendation.recommendation_engine import (
            PatientFinancialProfile,
            RecommendationEngine,
        )

        self.BillLineItem, self.CostCalculator, self.InsurancePolicy = BillLineItem, CostCalculator, InsurancePolicy
        self.EMICalculator = EMICalculator
        self.parser = BillParser()
        self.categorize, self.is_non_covered = categorize, is_non_covered
        self.detector = AnomalyDetector()
        self.PatientFinancialProfile, self.recommender = PatientFinancialProfile, RecommendationEngine()

    # --- OCR + parsing -------------------------------------------------

    @staticmethod
    def ocr_available() -> bool:
        return shutil.which("tesseract") is not None

    def ocr(self, file_path: str) -> str:
        if not self.ocr_available():
            raise OCRUnavailableError(
                "Tesseract OCR is not installed on this server. Run the app with Docker "
                "(it installs Tesseract) or enter the bill's line items manually."
            )
        from bill_app.ocr.ocr_extractor import OCRExtractor

        return OCRExtractor().extract(file_path)

    def parse(self, raw_text: str) -> dict:
        parsed = self.parser.parse(raw_text)
        data = asdict(parsed)
        stay = self._stay_days(parsed.admission_date, parsed.discharge_date)
        for item in data["line_items"]:
            item["quantity"] = self._quantity(item["description"], item["category"], stay)
            item["is_covered"] = not self.is_non_covered(item["description"])
        return data

    def describe_item(self, description: str, amount: float, quantity: Optional[int] = None,
                      category: Optional[str] = None) -> dict:
        category = category or self.categorize(description)
        return {
            "description": description,
            "amount": float(amount),
            "category": category,
            "quantity": quantity or self._quantity(description, category, None),
            "is_covered": not self.is_non_covered(description) and category != "cosmetic",
        }

    def _stay_days(self, admission: Optional[str], discharge: Optional[str]) -> Optional[int]:
        start, end = self._parse_date(admission), self._parse_date(discharge)
        if start and end and end >= start:
            return max((end - start).days, 1)
        return None

    def _parse_date(self, text: Optional[str]) -> Optional[datetime]:
        if not text:
            return None
        for fmt in self.DATE_FORMATS:
            try:
                return datetime.strptime(text.strip(), fmt)
            except ValueError:
                continue
        return None

    def _quantity(self, description: str, category: str, stay_days: Optional[int]) -> int:
        # The fair-price model prices room rent and nursing per day; read the
        # number of days from the line ("5 days") or from the admission dates.
        if category not in self.DAY_BASED:
            return 1
        match = re.search(r"(\d+)\s*days?", description, re.IGNORECASE)
        if match:
            return max(int(match.group(1)), 1)
        return stay_days or 1

    # --- detection + finance ------------------------------------------

    def analyze(self, items: list[dict], city_tier: str, hospital_type: str,
                policy: Optional[dict], profile: Optional[dict],
                emi_rate: float = 13.5, emi_months: int = 12) -> dict:
        detection = self.detector.analyze(
            [{k: i[k] for k in ("description", "category", "amount", "quantity")} for i in items],
            city_tier=city_tier, hospital_type=hospital_type,
        )

        insured = policy is not None
        bill_items = [
            self.BillLineItem(i["description"], i["category"], i["amount"], is_covered=insured and i["is_covered"])
            for i in items
        ]
        insurance_policy = self.InsurancePolicy(
            deductible=policy["deductible"], co_insurance_pct=policy["co_insurance_pct"],
            copay_flat=policy["copay_flat"],
            category_caps={"room_rent": policy["room_rent_cap"]} if policy.get("room_rent_cap") else {},
            overall_cap=policy.get("sum_insured"),
        ) if insured else self.InsurancePolicy()
        cost = self.CostCalculator(insurance_policy).calculate(bill_items)
        cost_dict = asdict(cost)

        oop = cost.patient_out_of_pocket
        emi = None
        tenures = []
        if oop > 0:
            emi_result = self.EMICalculator.calculate(oop, emi_rate, emi_months)
            emi = asdict(emi_result)
            tenures = self.EMICalculator.compare_tenures(oop, emi_rate, [6, 12, 24])

        recommendations = []
        if oop > 0:
            profile = profile or {}
            fin = self.PatientFinancialProfile(
                out_of_pocket_amount=oop,
                monthly_income=profile.get("monthly_income") or None,
                existing_monthly_debt_payments=profile.get("existing_monthly_debt", 0.0),
                has_credit_card=profile.get("has_credit_card", True),
                insurance_shortfall=cost.non_covered_amount + cost.category_cap_deductions if insured else 0.0,
            )
            recommendations = [asdict(r) for r in self.recommender.recommend(fin)]

        return {
            "detection": detection,
            "cost_breakdown": cost_dict,
            "emi": {"plan": emi, "tenure_comparison": tenures} if emi else {},
            "recommendations": recommendations,
        }

    def emi(self, principal: float, annual_rate: float, months: int) -> dict:
        return asdict(self.EMICalculator.calculate(principal, annual_rate, months))


# ---------------------------------------------------------------- registry


class ModelRegistry:
    """Loads every model once at startup; routes read from here."""

    def __init__(self):
        self.cost: Optional[CostModel] = None
        self.fraud: Optional[FraudModel] = None
        self.bill: Optional[BillAnalyzer] = None
        self.errors: dict[str, str] = {}
        self._lock = threading.Lock()

    def load(self):
        with self._lock:
            for attr, cls in (("cost", CostModel), ("fraud", FraudModel), ("bill", BillAnalyzer)):
                if getattr(self, attr) is not None:
                    continue
                try:
                    setattr(self, attr, cls())
                    self.errors.pop(attr, None)
                except Exception as exc:  # keep the API up; report in /api/health
                    self.errors[attr] = f"{type(exc).__name__}: {exc}"

    def status(self) -> dict:
        return {
            "cost": {"loaded": self.cost is not None, "name": CostModel.name, "error": self.errors.get("cost")},
            "fraud": {"loaded": self.fraud is not None, "name": FraudModel.name, "error": self.errors.get("fraud"),
                      "threshold": self.fraud.threshold if self.fraud else None},
            "bill": {"loaded": self.bill is not None, "name": BillAnalyzer.name, "error": self.errors.get("bill"),
                     "ocr_available": BillAnalyzer.ocr_available()},
        }


registry = ModelRegistry()
