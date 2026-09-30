"""
ml_bill_scorer.py
--------------------
Inference-time wrapper that combines both trained models to score every
line item on a parsed bill:

    Model 1 (RandomForestRegressor) -> predicts the fair/expected price
    Model 2 (IsolationForest)        -> flags the line item as anomalous
                                         or normal, using the fair-price
                                         prediction as one of its inputs

This is the module other code (the FastAPI layer, or the rest of the
pipeline) should import and call — it hides the two-model plumbing behind
one simple function: score_line_items(...).
"""

import os
import joblib
import numpy as np
import pandas as pd
from typing import List, Dict, Optional

_MODEL_DIR = os.path.dirname(os.path.abspath(__file__))


class MLBillScorer:
    def __init__(self,
                 fair_price_model_path: str = None,
                 anomaly_model_path: str = None):
        fair_price_model_path = fair_price_model_path or os.path.join(_MODEL_DIR, "fair_price_model.pkl")
        anomaly_model_path = anomaly_model_path or os.path.join(_MODEL_DIR, "lineitem_anomaly_model.pkl")

        fp_bundle = joblib.load(fair_price_model_path)
        self.fair_price_pipeline = fp_bundle["pipeline"]

        an_bundle = joblib.load(anomaly_model_path)
        self.anomaly_model = an_bundle["model"]
        self.encoder = an_bundle["encoder"]
        self.scaler = an_bundle["scaler"]
        self.categorical_features = an_bundle["categorical_features"]
        self.numeric_features = an_bundle["numeric_features"]

    def predict_fair_price(self, category: str, city_tier: str = "tier2",
                            hospital_type: str = "private", quantity: int = 1) -> float:
        row = pd.DataFrame([{
            "category": category, "city_tier": city_tier,
            "hospital_type": hospital_type, "quantity": quantity,
        }])
        return float(self.fair_price_pipeline.predict(row)[0])

    def score_line_items(self, line_items: List[Dict],
                          city_tier: str = "tier2",
                          hospital_type: str = "private") -> List[Dict]:
        """
        line_items: list of dicts like {"description": ..., "category": ..., "amount": ..., "quantity": 1}
        city_tier / hospital_type: context for this particular hospital/bill
          (pass these in from the bill upload form; defaulted here for
          standalone testing)

        Returns each item enriched with:
            fair_price_predicted, overcharge_ratio, overcharge_pct,
            ml_anomaly (bool), anomaly_score (float, lower = more anomalous),
            severity ("normal" | "review" | "high_risk")
        """
        if not line_items:
            return []

        rows = []
        for item in line_items:
            category = item.get("category", "other")
            # the fair-price model was trained on 6 known categories; fall
            # back to "procedure" pricing for anything unseen so we still
            # get a usable (if rough) estimate instead of failing
            model_category = category if category in (
                "room_rent", "procedure", "medicine", "diagnostic", "nursing", "consultation"
            ) else "procedure"
            quantity = item.get("quantity", 1)

            fair_price = self.predict_fair_price(model_category, city_tier, hospital_type, quantity)
            billed = float(item["amount"])
            overcharge_ratio = billed / fair_price if fair_price > 0 else 1.0

            rows.append({
                **item,
                "category_used_for_pricing": model_category,
                "fair_price_predicted": round(fair_price, 2),
                "overcharge_ratio": round(overcharge_ratio, 3),
                "overcharge_pct": round((overcharge_ratio - 1) * 100, 1),
                "billed_amount": billed,
                "quantity": quantity,
            })

        df = pd.DataFrame(rows)

        X_cat = self.encoder.transform(df[["category_used_for_pricing"]].rename(
            columns={"category_used_for_pricing": "category"}
        )).toarray()
        X_num = df[["billed_amount", "fair_price_predicted", "overcharge_ratio", "quantity"]].values
        X_num_scaled = self.scaler.transform(X_num)
        X = np.hstack([X_cat, X_num_scaled])

        predictions = self.anomaly_model.predict(X)          # 1 = normal, -1 = anomaly
        scores = self.anomaly_model.decision_function(X)      # higher = more normal

        results = []
        for i, row in df.iterrows():
            is_anomaly = predictions[i] == -1
            score = float(scores[i])

            if not is_anomaly and row["overcharge_pct"] < 25:
                severity = "normal"
            elif is_anomaly and row["overcharge_pct"] >= 60:
                severity = "high_risk"
            else:
                severity = "review"

            results.append({
                "description": row["description"],
                "category": row["category"],
                "billed_amount": row["billed_amount"],
                "fair_price_predicted": row["fair_price_predicted"],
                "overcharge_pct": row["overcharge_pct"],
                "ml_anomaly": bool(is_anomaly),
                "anomaly_score": round(score, 4),
                "severity": severity,
            })
        return results


if __name__ == "__main__":
    import json

    scorer = MLBillScorer()

    sample_bill_items = [
        {"description": "Room Rent (5 days)", "category": "room_rent", "amount": 25000, "quantity": 5},
        {"description": "Surgeon Fee - Appendectomy", "category": "procedure", "amount": 60000, "quantity": 1},
        {"description": "Paracetamol 500mg x10", "category": "medicine", "amount": 200, "quantity": 10},
        {"description": "CT Scan Chest", "category": "diagnostic", "amount": 22000, "quantity": 1},  # overpriced
        {"description": "Nursing Charges (5 days)", "category": "nursing", "amount": 5000, "quantity": 5},
        {"description": "Cosmetic Cream", "category": "cosmetic", "amount": 1500, "quantity": 1},
    ]

    results = scorer.score_line_items(sample_bill_items, city_tier="metro", hospital_type="multispeciality")
    print(json.dumps(results, indent=2))
