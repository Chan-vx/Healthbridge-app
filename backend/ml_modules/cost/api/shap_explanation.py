import joblib
import pandas as pd
import shap
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

MODEL_PATH = BASE_DIR / "models" / "cost_prediction_model.pkl"

pipeline = joblib.load(MODEL_PATH)

preprocessor = pipeline.named_steps["preprocessor"]
model = pipeline.named_steps["model"]


def explain_prediction(patient_data):

    data = pd.DataFrame([patient_data])

    transformed_data = preprocessor.transform(data)

    if hasattr(transformed_data, "toarray"):
        transformed_data = transformed_data.toarray()

    feature_names = preprocessor.get_feature_names_out()

    explainer = shap.TreeExplainer(model)

    shap_values = explainer.shap_values(transformed_data)

    prediction = model.predict(transformed_data)[0]

    # Store SHAP values
    raw_contributions = []

    for feature, value in zip(feature_names, shap_values[0]):

        clean_name = feature.replace("num__", "").replace("cat__", "")

        raw_contributions.append({
            "feature": clean_name,
            "shap_value": float(value)
        })

    # Combine one-hot encoded features
    combined = {}

    for item in raw_contributions:

        feature = item["feature"]
        value = item["shap_value"]

        if feature.startswith("smoker_"):
            original_feature = "smoker"

        elif feature.startswith("sex_"):
            original_feature = "sex"

        elif feature.startswith("region_"):
            original_feature = "region"

        else:
            original_feature = feature

        if original_feature not in combined:
            combined[original_feature] = 0

        combined[original_feature] += value

    contributions = []

    for feature, value in combined.items():

        contributions.append({
            "feature": feature,
            "shap_value": round(float(value), 2)
        })

    contributions.sort(
        key=lambda x: abs(x["shap_value"]),
        reverse=True
    )

    return {
        "predicted_expenses": round(float(prediction), 2),
        "feature_contributions": contributions
    }