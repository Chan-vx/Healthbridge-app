"""
anomaly_detector.py
----------------------
Combines TWO complementary detection approaches on a parsed bill's line items:

1. DUPLICATE CHARGE DETECTION (rule-based, fuzzy string matching)
   Isolation Forest / regression models don't reliably catch "this exact
   line item was billed twice" — that is a text-similarity problem, not a
   price/anomaly problem, so it stays rule-based and explainable.

2. OVERCHARGE / UNUSUAL PRICING DETECTION (ML-powered)
   Delegates to MLBillScorer (app/ml/ml_bill_scorer.py), which uses:
     - a RandomForestRegressor to predict each item's fair market price
     - an IsolationForest to flag items whose (price, category, overcharge
       ratio) combination looks anomalous compared to normal billing patterns
   This replaces a earlier fixed reference-price lookup table with a model
   that generalizes to items it has never seen an exact price for before.
"""

import sys
import os
from dataclasses import dataclass
from typing import List, Dict, Optional
from difflib import SequenceMatcher

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml"))
from ml_bill_scorer import MLBillScorer  # noqa: E402


@dataclass
class DuplicateFlag:
    description: str
    amount: float
    matched_with: str
    similarity_pct: float
    severity: str


class AnomalyDetector:
    def __init__(self, similarity_threshold: float = 0.82, ml_scorer: Optional[MLBillScorer] = None):
        self.similarity_threshold = similarity_threshold
        self.ml_scorer = ml_scorer or MLBillScorer()

    @staticmethod
    def _similar(a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()

    def find_duplicates(self, line_items: List[Dict]) -> List[DuplicateFlag]:
        flags = []
        seen = []
        for item in line_items:
            desc = item["description"]
            for prior in seen:
                sim = self._similar(desc, prior["description"])
                if sim >= self.similarity_threshold:
                    flags.append(DuplicateFlag(
                        description=desc, amount=item["amount"],
                        matched_with=prior["description"],
                        similarity_pct=round(sim * 100, 1),
                        severity="high" if sim > 0.95 else "medium",
                    ))
            seen.append(item)
        return flags

    def analyze(self, line_items: List[Dict], city_tier: str = "tier2",
                hospital_type: str = "private") -> Dict:
        duplicates = self.find_duplicates(line_items)
        ml_scores = self.ml_scorer.score_line_items(line_items, city_tier=city_tier, hospital_type=hospital_type)

        high_risk_items = [i for i in ml_scores if i["severity"] == "high_risk"]
        review_items = [i for i in ml_scores if i["severity"] == "review"]

        return {
            "duplicate_charges": [f.__dict__ for f in duplicates],
            "ml_price_analysis": ml_scores,
            "summary": {
                "total_line_items": len(line_items),
                "duplicate_count": len(duplicates),
                "high_risk_count": len(high_risk_items),
                "review_count": len(review_items),
                "flagged_amount_total": round(
                    sum(f.amount for f in duplicates) + sum(i["billed_amount"] for i in high_risk_items), 2
                ),
            },
        }


if __name__ == "__main__":
    import json

    bill_items = [
        {"description": "Paracetamol 500mg", "category": "medicine", "amount": 200, "quantity": 10},
        {"description": "Paracetamol 500mg tablet", "category": "medicine", "amount": 200, "quantity": 10},
        {"description": "CT Scan Chest", "category": "diagnostic", "amount": 22000, "quantity": 1},
        {"description": "Room Rent (5 days)", "category": "room_rent", "amount": 25000, "quantity": 5},
        {"description": "Surgeon Fee", "category": "procedure", "amount": 60000, "quantity": 1},
    ]

    detector = AnomalyDetector()
    result = detector.analyze(bill_items, city_tier="metro", hospital_type="multispeciality")
    print(json.dumps(result, indent=2))
