import joblib
import pandas as pd
import shap

from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"


# ============================================================
# LOAD MODELS
# ============================================================

MODEL = joblib.load(
    MODELS_DIR / "robust_xgboost_fraud.pkl"
)

PREPROCESSOR = joblib.load(
    MODELS_DIR / "robust_preprocessor.pkl"
)

ISOLATION_MODEL = joblib.load(
    MODELS_DIR / "isolation_forest.pkl"
)

ANOMALY_SCALER = joblib.load(
    MODELS_DIR / "anomaly_scaler.pkl"
)

THRESHOLD = joblib.load(
    MODELS_DIR / "fraud_threshold.pkl"
)

EXPLAINER = shap.TreeExplainer(MODEL)


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="HealthBridge AI/ML API",
    description="Healthcare insurance fraud detection, risk scoring and explainability API",
    version="3.0"
)


# ============================================================
# CLAIM INPUT
# ============================================================

class ClaimRequest(BaseModel):

    ClaimAmount: float = Field(gt=0)
    PatientAge: int = Field(ge=0, le=120)

    PatientGender: str
    ProviderSpecialty: str

    PatientIncome: float = Field(ge=0)

    PatientMaritalStatus: str
    PatientEmploymentStatus: str
    ProviderLocation: str
    ClaimType: str
    ClaimSubmissionMethod: str

    ClaimYear: int = Field(ge=2000, le=2100)
    ClaimMonth: int = Field(ge=1, le=12)
    ClaimDayOfWeek: int = Field(ge=0, le=6)


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():

    return {
        "project": "HealthBridge",
        "module": "AI/ML Fraud Detection",
        "status": "running",
        "version": "3.0"
    }


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health_check():

    return {
        "status": "healthy",
        "xgboost": "loaded",
        "isolation_forest": "loaded",
        "anomaly_scaler": "loaded",
        "threshold": "loaded",
        "shap": "loaded"
    }


# ============================================================
# PREDICTION
# ============================================================

@app.post("/predict")
def predict(claim: ClaimRequest):

    try:

        # ----------------------------------------------------
        # Create input dataframe
        # ----------------------------------------------------

        data = pd.DataFrame([{
            "ClaimAmount": claim.ClaimAmount,
            "PatientAge": claim.PatientAge,
            "PatientGender": claim.PatientGender,
            "ProviderSpecialty": claim.ProviderSpecialty,
            "PatientIncome": claim.PatientIncome,
            "PatientMaritalStatus": claim.PatientMaritalStatus,
            "PatientEmploymentStatus": claim.PatientEmploymentStatus,
            "ProviderLocation": claim.ProviderLocation,
            "ClaimType": claim.ClaimType,
            "ClaimSubmissionMethod": claim.ClaimSubmissionMethod,
            "ClaimYear": claim.ClaimYear,
            "ClaimMonth": claim.ClaimMonth,
            "ClaimDayOfWeek": claim.ClaimDayOfWeek
        }])


        # ----------------------------------------------------
        # Preprocessing
        # ----------------------------------------------------

        processed_data = PREPROCESSOR.transform(data)


        # ----------------------------------------------------
        # XGBoost fraud probability
        # ----------------------------------------------------

        fraud_probability = float(
            MODEL.predict_proba(processed_data)[0][1]
        )


        # ----------------------------------------------------
        # Fraud prediction using optimized threshold
        # ----------------------------------------------------

        fraud_prediction = int(
            fraud_probability >= THRESHOLD
        )


        # ----------------------------------------------------
        # Isolation Forest anomaly detection
        # ----------------------------------------------------

        raw_anomaly_score = float(
            -ISOLATION_MODEL.decision_function(processed_data)[0]
        )

        anomaly_score = float(
            ANOMALY_SCALER.transform(
                [[raw_anomaly_score]]
            )[0][0]
        )

        anomaly_score = max(
            0.0,
            min(1.0, anomaly_score)
        )


        # ----------------------------------------------------
        # Hybrid risk score
        # ----------------------------------------------------

        hybrid_score = (
            0.80 * fraud_probability
            + 0.20 * anomaly_score
        )


        # ----------------------------------------------------
        # Risk classification
        # ----------------------------------------------------

        if hybrid_score >= 0.70:

            risk_level = "HIGH"
            recommendation = "Manual Investigation"

        elif hybrid_score >= 0.40:

            risk_level = "MEDIUM"
            recommendation = "Additional Verification"

        else:

            risk_level = "LOW"
            recommendation = "Normal Processing"


        # ----------------------------------------------------
        # SHAP explainability
        # ----------------------------------------------------

        shap_input = processed_data

        if hasattr(shap_input, "toarray"):
            shap_input = shap_input.toarray()

        feature_names = PREPROCESSOR.get_feature_names_out()

        shap_input = pd.DataFrame(
            shap_input,
            columns=feature_names
        )

        shap_values = EXPLAINER.shap_values(shap_input)

        if isinstance(shap_values, list):
            shap_values = shap_values[0]

        shap_values = shap_values[0]


        # ----------------------------------------------------
        # Rank SHAP features
        # ----------------------------------------------------

        explanation = pd.DataFrame({
            "Feature": feature_names,
            "SHAP": shap_values
        })

        explanation["Impact"] = explanation["SHAP"].abs()

        explanation = explanation.sort_values(
            "Impact",
            ascending=False
        )


        top_features = []

        for _, row in explanation.head(5).iterrows():

            feature = row["Feature"]

            feature = (
                feature
                .replace("numeric__", "")
                .replace("categorical__", "")
            )

            top_features.append({
                "feature": feature,
                "impact": round(
                    float(row["SHAP"]),
                    4
                ),
                "direction": (
                    "increases fraud risk"
                    if row["SHAP"] > 0
                    else "decreases fraud risk"
                )
            })


        # ----------------------------------------------------
        # Final response
        # ----------------------------------------------------

        return {

            "fraud_probability": round(
                fraud_probability,
                4
            ),

            "anomaly_score": round(
                anomaly_score,
                4
            ),

            "hybrid_risk_score": round(
                hybrid_score,
                4
            ),

            "fraud_prediction": fraud_prediction,

            "risk_level": risk_level,

            "recommendation": recommendation,

            "top_factors": top_features
        }


    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Prediction failed: {str(e)}"
        )