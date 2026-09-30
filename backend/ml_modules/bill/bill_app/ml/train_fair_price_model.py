"""
train_fair_price_model.py
----------------------------
MODEL 1 of 2 in the Bill & Finance ML layer: FAIR PRICE PREDICTOR

Trains a RandomForestRegressor to predict the "fair market price" of a
medical bill line item, given:
    - category        (room_rent, procedure, medicine, diagnostic, nursing, consultation)
    - city_tier        (metro / tier2 / tier3)
    - hospital_type    (government / private / multispeciality / premium)
    - quantity          (number of units billed, e.g. 5 tablets, 3 diagnostic tests)

Why RandomForestRegressor:
    - The relationship between these features and price is NON-LINEAR
      (e.g. a "premium" hospital in a "metro" city doesn't just add the two
      multipliers, the combined effect compounds) — tree ensembles capture
      this kind of interaction naturally, without manually engineering
      interaction terms the way plain Linear Regression would need.
    - Categorical features (category, city_tier, hospital_type) are handled
      cleanly via one-hot encoding + trees, with no assumption of ordering.
    - Robust to outliers/noise in the training data, and gives free
      feature-importance scores for explainability (similar in spirit to
      Member 1's SHAP explanations, but lightweight enough to compute
      instantly for every prediction).
    - Fast to train and predict, which matters because this model is called
      once per bill line item, potentially many times per bill.

Output: fair_price_model.pkl (model + encoders bundled together)
"""

import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline

from generate_pricing_dataset import generate_pricing_dataset

RANDOM_STATE = 42

CATEGORICAL_FEATURES = ["category", "city_tier", "hospital_type"]
NUMERIC_FEATURES = ["quantity"]
TARGET = "fair_price"


def build_pipeline() -> Pipeline:
    preprocessor = ColumnTransformer(transformers=[
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ], remainder="passthrough")  # numeric features pass through unchanged

    model = RandomForestRegressor(
        n_estimators=300,
        max_depth=12,
        min_samples_leaf=4,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )

    return Pipeline(steps=[("preprocess", preprocessor), ("model", model)])


def train():
    print("Generating training data...")
    df = generate_pricing_dataset(n_samples=6000)

    X = df[CATEGORICAL_FEATURES + NUMERIC_FEATURES]
    y = df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE
    )

    print("Training RandomForestRegressor...")
    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)

    # ---- Evaluate ----
    y_pred = pipeline.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    mape = np.mean(np.abs((y_test - y_pred) / y_test)) * 100

    print(f"\nModel performance on held-out test set:")
    print(f"  MAE  : Rs. {mae:,.2f}")
    print(f"  MAPE : {mape:.2f}%")
    print(f"  R^2  : {r2:.4f}")

    # ---- Feature importance (explainability) ----
    ohe = pipeline.named_steps["preprocess"].named_transformers_["cat"]
    feature_names = list(ohe.get_feature_names_out(CATEGORICAL_FEATURES)) + NUMERIC_FEATURES
    importances = pipeline.named_steps["model"].feature_importances_
    importance_df = pd.DataFrame({"feature": feature_names, "importance": importances}) \
        .sort_values("importance", ascending=False)

    print("\nTop feature importances:")
    print(importance_df.head(10).to_string(index=False))

    joblib.dump({
        "pipeline": pipeline,
        "categorical_features": CATEGORICAL_FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "metrics": {"mae": mae, "mape": mape, "r2": r2},
        "feature_importance": importance_df.to_dict(orient="records"),
    }, "fair_price_model.pkl")
    print("\nModel saved to fair_price_model.pkl")

    return pipeline


def predict_fair_price(pipeline, category, city_tier, hospital_type, quantity=1) -> float:
    row = pd.DataFrame([{
        "category": category, "city_tier": city_tier,
        "hospital_type": hospital_type, "quantity": quantity,
    }])
    return float(pipeline.predict(row)[0])


if __name__ == "__main__":
    pipeline = train()

    print("\n--- Example predictions ---")
    examples = [
        ("procedure", "metro", "premium", 1),
        ("procedure", "tier3", "government", 1),
        ("diagnostic", "metro", "multispeciality", 1),
        ("medicine", "tier2", "private", 10),
    ]
    for cat, city, htype, qty in examples:
        price = predict_fair_price(pipeline, cat, city, htype, qty)
        print(f"  {cat:12s} | {city:7s} | {htype:15s} | qty={qty:2d}  ->  Rs. {price:,.2f}")
