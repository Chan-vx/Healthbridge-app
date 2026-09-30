"""
recommendation_engine.py
--------------------------
Rule-based engine ranking realistic financing options for a patient's
out-of-pocket amount: pay-in-full, hospital no-cost EMI, bank/NBFC loan,
credit card EMI, government/charity scheme, insurance appeal.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calculators"))
from emi_calculator import EMICalculator  # noqa: E402


@dataclass
class PatientFinancialProfile:
    out_of_pocket_amount: float
    monthly_income: Optional[float] = None
    is_emergency: bool = True
    existing_monthly_debt_payments: float = 0.0
    has_credit_card: bool = True
    insurance_shortfall: float = 0.0


@dataclass
class Recommendation:
    option: str
    suitability_score: float
    reasoning: str
    details: Dict = field(default_factory=dict)


class RecommendationEngine:
    MAX_DEBT_TO_INCOME_RATIO = 0.40

    def recommend(self, profile: PatientFinancialProfile) -> List[Recommendation]:
        recs = [self._pay_in_full(profile), self._hospital_emi(profile), self._bank_nbfc_loan(profile)]
        if profile.has_credit_card:
            recs.append(self._credit_card_emi(profile))
        gov_scheme = self._government_scheme(profile)
        if gov_scheme:
            recs.append(gov_scheme)
        if profile.insurance_shortfall > 0:
            recs.append(self._insurance_appeal(profile))
        recs.sort(key=lambda r: r.suitability_score, reverse=True)
        return recs

    def _pay_in_full(self, p: PatientFinancialProfile) -> Recommendation:
        if p.monthly_income is None:
            return Recommendation("Pay in Full", 30.0,
                                   "Income not provided — cannot assess affordability of paying in full.",
                                   {"amount": p.out_of_pocket_amount, "interest_cost": 0.0})
        affordable = p.out_of_pocket_amount <= p.monthly_income * 1.5
        return Recommendation(
            "Pay in Full", 85.0 if affordable else 20.0,
            "Out-of-pocket amount is within ~1.5x monthly income; paying in full avoids interest."
            if affordable else
            "Out-of-pocket amount is large relative to income — paying in full would strain finances.",
            {"amount": p.out_of_pocket_amount, "interest_cost": 0.0},
        )

    def _hospital_emi(self, p: PatientFinancialProfile) -> Recommendation:
        emi_preview = EMICalculator.calculate(p.out_of_pocket_amount, 0, 6)
        return Recommendation(
            "Hospital No-Cost EMI", 80.0,
            "Many hospitals offer 0%/no-cost EMI tie-ups with NBFCs for medical bills — "
            "worth checking with the billing desk before opting for a bank loan.",
            {"estimated_monthly_emi_6mo": emi_preview.monthly_emi,
             "typical_interest_rate": "0% (subsidized by hospital/NBFC tie-up)",
             "note": "Availability and eligibility vary by hospital — confirm directly."},
        )

    def _bank_nbfc_loan(self, p: PatientFinancialProfile) -> Recommendation:
        annual_rate = 13.5
        emi_12mo = EMICalculator.calculate(p.out_of_pocket_amount, annual_rate, 12)
        score = 65.0
        note = ""
        if p.monthly_income:
            new_dti = (p.existing_monthly_debt_payments + emi_12mo.monthly_emi) / p.monthly_income
            if new_dti > self.MAX_DEBT_TO_INCOME_RATIO:
                score -= 25
                note = f" Caution: this EMI would push total debt payments to {new_dti*100:.0f}% of monthly income (recommended limit ~40%)."
        return Recommendation(
            "Bank / NBFC Medical Loan", max(score, 10.0),
            "A dedicated medical loan spreads the cost over 6-24 months at market interest rates, "
            "useful when hospital EMI isn't available." + note,
            {"annual_interest_rate": annual_rate, "tenure_options_months": [6, 12, 24],
             "emi_12_months": emi_12mo.monthly_emi, "total_interest_12_months": emi_12mo.total_interest},
        )

    def _credit_card_emi(self, p: PatientFinancialProfile) -> Recommendation:
        annual_rate = 15.0
        emi_6mo = EMICalculator.calculate(p.out_of_pocket_amount, annual_rate, 6)
        return Recommendation(
            "Credit Card EMI Conversion", 55.0,
            "Fast to set up (no new loan approval needed) but typically carries a higher "
            "interest rate than a dedicated medical/personal loan.",
            {"annual_interest_rate": annual_rate, "emi_6_months": emi_6mo.monthly_emi,
             "total_interest_6_months": emi_6mo.total_interest},
        )

    def _government_scheme(self, p: PatientFinancialProfile) -> Optional[Recommendation]:
        if p.monthly_income is not None and p.monthly_income < 25000 and p.out_of_pocket_amount > 50000:
            return Recommendation(
                "Government Health Scheme / Charitable Assistance", 75.0,
                "Given the income level and bill size, this patient may be eligible for schemes "
                "like Ayushman Bharat (PM-JAY), state health schemes, or hospital charitable/CSR funds. "
                "Worth checking eligibility before financing privately.",
                {"note": "Eligibility depends on state, income category, and hospital empanelment."},
            )
        return None

    def _insurance_appeal(self, p: PatientFinancialProfile) -> Recommendation:
        return Recommendation(
            "Insurance Claim Appeal / Reimbursement Follow-up", 70.0,
            f"Rs.{p.insurance_shortfall:.0f} was not covered by insurance — if due to a category cap, "
            "sub-limit, or documentation issue, an appeal or reimbursement claim may recover part of "
            "this before resorting to a loan.",
            {"shortfall_amount": p.insurance_shortfall},
        )
