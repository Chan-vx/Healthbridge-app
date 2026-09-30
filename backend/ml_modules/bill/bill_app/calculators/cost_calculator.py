"""
cost_calculator.py
-------------------
Computes the patient-facing cost breakdown:
    Total Billed  ->  Insurance Coverage  ->  Patient Out-of-Pocket

Models real insurance mechanics: deductible, co-insurance %, flat copay,
per-category coverage caps, and an overall claim/sum-insured cap.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class BillLineItem:
    description: str
    category: str
    amount: float
    is_covered: bool = True


@dataclass
class InsurancePolicy:
    deductible: float = 0.0
    co_insurance_pct: float = 0.0
    copay_flat: float = 0.0
    category_caps: Dict[str, float] = field(default_factory=dict)
    overall_cap: Optional[float] = None


@dataclass
class CostBreakdown:
    total_billed: float
    covered_amount: float
    non_covered_amount: float
    deductible_applied: float
    category_cap_deductions: float
    co_insurance_patient_share: float
    copay: float
    insurance_pays: float
    patient_out_of_pocket: float
    line_item_details: List[Dict]


class CostCalculator:
    def __init__(self, policy: InsurancePolicy):
        self.policy = policy

    def calculate(self, line_items: List[BillLineItem]) -> CostBreakdown:
        total_billed = sum(item.amount for item in line_items)
        covered_items = [i for i in line_items if i.is_covered]
        non_covered_items = [i for i in line_items if not i.is_covered]
        non_covered_amount = sum(i.amount for i in non_covered_items)

        capped_covered_total = sum(i.amount for i in covered_items)
        details = [
            {"description": i.description, "category": i.category, "billed": i.amount, "covered": True}
            for i in covered_items
        ] + [
            {"description": i.description, "category": i.category, "billed": i.amount, "covered": False}
            for i in non_covered_items
        ]

        category_totals: Dict[str, float] = {}
        for item in covered_items:
            category_totals[item.category] = category_totals.get(item.category, 0.0) + item.amount

        category_cap_deductions = 0.0
        for cat, cap in self.policy.category_caps.items():
            billed_in_cat = category_totals.get(cat, 0.0)
            if billed_in_cat > cap:
                excess = billed_in_cat - cap
                category_cap_deductions += excess
                capped_covered_total -= excess

        covered_amount = max(capped_covered_total, 0.0)
        deductible_applied = min(self.policy.deductible, covered_amount)
        remaining_after_deductible = covered_amount - deductible_applied
        co_insurance_patient_share = remaining_after_deductible * (self.policy.co_insurance_pct / 100.0)
        insurance_pays = remaining_after_deductible - co_insurance_patient_share

        if self.policy.overall_cap is not None and insurance_pays > self.policy.overall_cap:
            overflow = insurance_pays - self.policy.overall_cap
            insurance_pays = self.policy.overall_cap
            co_insurance_patient_share += overflow

        # Integration fix: the copay is part of the patient's share, so it must
        # also come off what insurance pays (otherwise insurance + patient
        # exceeds the bill by the copay amount).
        copay = min(self.policy.copay_flat, insurance_pays)
        insurance_pays -= copay
        patient_out_of_pocket = (
            non_covered_amount + deductible_applied + co_insurance_patient_share
            + copay + category_cap_deductions
        )

        return CostBreakdown(
            total_billed=round(total_billed, 2),
            covered_amount=round(covered_amount, 2),
            non_covered_amount=round(non_covered_amount, 2),
            deductible_applied=round(deductible_applied, 2),
            category_cap_deductions=round(category_cap_deductions, 2),
            co_insurance_patient_share=round(co_insurance_patient_share, 2),
            copay=round(copay, 2),
            insurance_pays=round(insurance_pays, 2),
            patient_out_of_pocket=round(patient_out_of_pocket, 2),
            line_item_details=details,
        )
