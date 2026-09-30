"""
emi_calculator.py
------------------
Reducing-balance EMI calculation + full amortization schedule.
"""

from dataclasses import dataclass
from typing import List, Dict


@dataclass
class EMIResult:
    principal: float
    annual_interest_rate: float
    tenure_months: int
    monthly_emi: float
    total_payment: float
    total_interest: float
    schedule: List[Dict]


class EMICalculator:
    @staticmethod
    def calculate(principal: float, annual_rate_pct: float, tenure_months: int) -> EMIResult:
        if principal <= 0 or tenure_months <= 0:
            raise ValueError("principal and tenure_months must be positive")

        r = (annual_rate_pct / 12) / 100
        if annual_rate_pct == 0:
            emi = principal / tenure_months
        else:
            emi = principal * r * (1 + r) ** tenure_months / ((1 + r) ** tenure_months - 1)

        schedule, balance, total_interest = [], principal, 0.0
        for month in range(1, tenure_months + 1):
            interest_component = balance * r if annual_rate_pct > 0 else 0.0
            principal_component = emi - interest_component
            balance = max(balance - principal_component, 0.0)
            total_interest += interest_component
            schedule.append({
                "month": month, "emi": round(emi, 2),
                "principal_component": round(principal_component, 2),
                "interest_component": round(interest_component, 2),
                "remaining_balance": round(balance, 2),
            })

        return EMIResult(
            principal=round(principal, 2), annual_interest_rate=annual_rate_pct,
            tenure_months=tenure_months, monthly_emi=round(emi, 2),
            total_payment=round(emi * tenure_months, 2), total_interest=round(total_interest, 2),
            schedule=schedule,
        )

    @staticmethod
    def compare_tenures(principal: float, annual_rate_pct: float, tenure_options: List[int]) -> List[Dict]:
        results = []
        for months in tenure_options:
            r = EMICalculator.calculate(principal, annual_rate_pct, months)
            results.append({
                "tenure_months": months, "monthly_emi": r.monthly_emi,
                "total_payment": r.total_payment, "total_interest": r.total_interest,
            })
        return results
