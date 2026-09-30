"""
train_lineitem_anomaly_model.py
----------------------------------
MODEL 2 of 2 in the Bill & Finance ML layer: LINE-ITEM ANOMALY DETECTOR

Trains an Isolation Forest to flag unusual/suspicious bill line items,
using engineered features that combine raw billing data WITH the Fair
Price Predictor's output:

    - billed_amount            : what was actually charged
    - fair_price_predicted     : what Model 1 (RandomForest) expects it to cost
    - overcharge_ratio         : billed_amount / fair_price_predicted
    - quantity
    - category (one-hot)

Why Isolation Forest (unsupervised) instead of a supervised classifier:
    - Real-world fraud/billing-error labels are scarce and expensive to get
      (hospitals rarely label "this line item was an error/fraud"). Isolation
      Forest needs NO labels — it learns what "normal" combinations of these
      features look like from the training distribution and flags anything
      that doesn't fit, which matches the data we actually have access to.
    - It isolates anomalies by randomly partitioning the feature space —
      anomalies (rare, extreme combinations) get isolated in fewer random
      splits than normal points, which is exactly the "this doesn't look
      like anything else in the bill" signal we want for overcharge/fraud
      detection.
    - Same model family used for Member 2's claim-level fraud detection,
      kept consistent here but applied at the line-item level with
      different, bill-specific engineered features.

This is trained on the SAME synthetic pricing dataset as Model 1, with a
small fraction of synthetically injected overcharged/undercharged items so
the model has genuine outliers to learn to isolate, then evaluated against
those known injected anomalies.

Output: lineitem_anomaly_model.pkl
"""

import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler, OneHotEncoder

from generate_pricing_dataset import generate_pricing_dataset

RANDOM_STATE = 42
np.random.seed(RANDOM_STATE)

CATEGORICAL_FEATURES = ["category"]
NUMERIC_FEATURES = ["billed_amount", "fair_price_predicted", "overcharge_ratio", "quantity"]


def build_training_frame(fair_price_bundle, n_samples: int = 5000, anomaly_frac: float = 0.06) -> pd.DataFrame:
    """
    Builds a feature frame of billed line items where the vast majority are
    priced close to their model-predicted fair price (normal), and a small
    fraction are injected anomalies (billed far above/below fair price, or
    with implausible quantities) — for the Isolation Forest to learn from
    and for us to sanity-check its recall against.
    """
    pipeline = fair_price_bundle["pipeline"]
    df = generate_pricing_dataset(n_samples=n_samples)

    fair_prices = pipeline.predict(df[["category", "city_tier", "hospital_type", "quantity"]])
    df["fair_price_predicted"] = fair_prices

    n_anomalies = int(n_samples * anomaly_frac)
    anomaly_idx = np.random.choice(df.index, size=n_anomalies, replace=False)
    is_injected_anomaly = pd.Series(False, index=df.index)
    is_injected_anomaly.loc[anomaly_idx] = True

    # normal items: billed close to fair price (+/- ~15%)
    billed = df["fair_price_predicted"] * np.random.normal(1.0, 0.15, size=len(df))

    # anomalous items: billed 2x-6x fair price (overcharge) — the failure
    # mode this model is specifically meant to catch
    overcharge_multiplier = np.random.uniform(2.0, 6.0, size=len(df))
    billed[is_injected_anomaly] = (
        df.loc[is_injected_anomaly, "fair_price_predicted"] * overcharge_multiplier[is_injected_anomaly]
    )

    df["billed_amount"] = billed.round(2)
    df["overcharge_ratio"] = (df["billed_amount"] / df["fair_price_predicted"]).round(3)
    df["is_injected_anomaly"] = is_injected_anomaly

    return df


def train(fair_price_model_path: str = "fair_price_model.pkl"):
    fair_price_bundle = joblib.load(fair_price_model_path)

    print("Building line-item training frame using the Fair Price model...")
    df = build_training_frame(fair_price_bundle, n_samples=5000, anomaly_frac=0.06)

    encoder = OneHotEncoder(handle_unknown="ignore")
    X_cat = encoder.fit_transform(df[CATEGORICAL_FEATURES]).toarray()
    X_num = df[NUMERIC_FEATURES].values

    scaler = StandardScaler()
    X_num_scaled = scaler.fit_transform(X_num)

    X = np.hstack([X_cat, X_num_scaled])

    print("Training Isolation Forest...")
    model = IsolationForest(
        n_estimators=250,
        contamination=0.06,   # matches the injected anomaly fraction
        max_samples="auto",
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    model.fit(X)

    # ---- Evaluate against the known injected anomalies ----
    predictions = model.predict(X)          # 1 = normal, -1 = anomaly
    predicted_anomaly = predictions == -1
    actual_anomaly = df["is_injected_anomaly"].values

    tp = int(np.sum(predicted_anomaly & actual_anomaly))
    fp = int(np.sum(predicted_anomaly & ~actual_anomaly))
    fn = int(np.sum(~predicted_anomaly & actual_anomaly))
    tn = int(np.sum(~predicted_anomaly & ~actual_anomaly))

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    print(f"\nEvaluation against {int(actual_anomaly.sum())} known injected overcharge anomalies:")
    print(f"  Precision : {precision:.3f}")
    print(f"  Recall    : {recall:.3f}")
    print(f"  F1-score  : {f1:.3f}")
    print(f"  Confusion matrix  TP={tp}  FP={fp}  FN={fn}  TN={tn}")

    joblib.dump({
        "model": model,
        "encoder": encoder,
        "scaler": scaler,
        "categorical_features": CATEGORICAL_FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "metrics": {"precision": precision, "recall": recall, "f1": f1},
    }, "lineitem_anomaly_model.pkl")
    print("\nModel saved to lineitem_anomaly_model.pkl")

    return model, encoder, scaler


if __name__ == "__main__":
    train()
