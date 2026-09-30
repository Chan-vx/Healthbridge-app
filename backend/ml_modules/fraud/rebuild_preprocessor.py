"""
Re-fits Member 2's robust preprocessor (src/11_robust_preprocess.py) under the
pinned scikit-learn version. The original robust_preprocessor.pkl was saved with
scikit-learn 1.6.1 and cannot be unpickled by 1.9.x.

Same data, same columns, same stratified split (random_state=42), same
StandardScaler + OneHotEncoder, so the fitted transformer is identical and the
existing robust_xgboost_fraud.pkl / isolation_forest.pkl stay valid.
"""

from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler

BASE_DIR = Path(__file__).resolve().parent
EXCEL_PATH = BASE_DIR / "data" / "Health Insurance Fraud Claims.xlsx"
OUTPUT_PATH = BASE_DIR / "models" / "robust_preprocessor.pkl"

NUMERIC_FEATURES = [
    "ClaimAmount", "PatientAge", "PatientIncome",
    "ClaimYear", "ClaimMonth", "ClaimDayOfWeek",
]
CATEGORICAL_FEATURES = [
    "PatientGender", "ProviderSpecialty", "PatientMaritalStatus",
    "PatientEmploymentStatus", "ProviderLocation", "ClaimType",
    "ClaimSubmissionMethod",
]
REMOVE_COLUMNS = [
    "ClaimID", "PatientID", "ProviderID", "ClaimDate", "Cluster",
    "ClaimStatus", "ClaimLegitimacy", "DiagnosisCode", "ProcedureCode",
]


def load_split():
    df = pd.read_excel(EXCEL_PATH)
    df["Fraud"] = (df["ClaimLegitimacy"] == "Fraud").astype(int)
    df["ClaimDate"] = pd.to_datetime(df["ClaimDate"])
    df["ClaimYear"] = df["ClaimDate"].dt.year
    df["ClaimMonth"] = df["ClaimDate"].dt.month
    df["ClaimDayOfWeek"] = df["ClaimDate"].dt.dayofweek
    df = df.drop(columns=REMOVE_COLUMNS)

    X = df.drop(columns=["Fraud"])
    y = df["Fraud"]
    return train_test_split(X, y, test_size=0.20, random_state=42, stratify=y)


def build():
    X_train, X_test, y_train, y_test = load_split()
    preprocessor = ColumnTransformer(transformers=[
        ("numeric", StandardScaler(), NUMERIC_FEATURES),
        ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=True),
         CATEGORICAL_FEATURES),
    ])
    preprocessor.fit(X_train)
    joblib.dump(preprocessor, OUTPUT_PATH)
    return preprocessor, X_test, y_test


if __name__ == "__main__":
    pre, X_test, _ = build()
    print("Saved", OUTPUT_PATH, "features:", len(pre.get_feature_names_out()))
