"""
Evaluates every model the platform uses on data it was not trained on, and writes
app/data/model_performance.json for the "Model performance" page.

Each section reproduces the member's own train/test split (same file, same columns,
same random_state), so the test rows are exactly the ones the model never saw:

    Member 1  cost        data/insurance.csv, 80/20 split, random_state=42  (notebook)
    Member 2  fraud       Health Insurance Fraud Claims.xlsx, stratified 80/20, random_state=42
                          (src/11_robust_preprocess.py); threshold chosen on a validation split
                          of the training rows (src/15_threshold_optimization.py)
    Member 3  bill        fair-price model: generate_pricing_dataset 80/20, random_state=42
                          anomaly model: a NEW synthetic batch with injected overcharges
                          (the member's script scored its own training rows)
                          OCR: every sample bill in test_samples/ against the values printed on it
    Member 4  authenticity  every fake and genuine sample bill uploaded through the real API
                          on a throwaway database seeded with the demo data

Run inside the backend image (takes a few minutes, OCR is the slow part):

    docker compose run --rm -v ./backend:/srv -v ./test_samples:/srv/test_samples backend python evaluation/evaluate_models.py
"""

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(ROOT))

# authenticity runs the real app on a throwaway SQLite database, never the app's own database
# (docker compose passes its DATABASE_URL in); set before importing app
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'eval.db')}"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp()
os.environ["SEED_DEMO"] = "false"

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    average_precision_score, confusion_matrix, f1_score, mean_absolute_error, mean_squared_error,
    precision_score, r2_score, recall_score, roc_auc_score, roc_curve,
)
from sklearn.model_selection import train_test_split  # noqa: E402

ML = ROOT / "ml_modules"
SAMPLES = Path(os.environ.get("SAMPLES_DIR", ROOT / "test_samples"))
if not SAMPLES.exists():
    SAMPLES = ROOT.parent / "test_samples"
OUT = ROOT / "app" / "data" / "model_performance.json"
USD_TO_INR = 83.0


def r(x, n=4):
    return None if x is None else round(float(x), n)


def binary_metrics(y, pred, score=None):
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    out = {
        "precision": r(precision_score(y, pred, zero_division=0)),
        "recall": r(recall_score(y, pred, zero_division=0)),
        "f1": r(f1_score(y, pred, zero_division=0)),
        "accuracy": r((tp + tn) / len(y)),
        "false_positive_rate": r(fp / (fp + tn) if fp + tn else 0),
        "confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }
    if score is not None:
        out["roc_auc"] = r(roc_auc_score(y, score))
        out["pr_auc"] = r(average_precision_score(y, score))
    return out


def roc_points(y, score, n=60):
    fpr, tpr, _ = roc_curve(y, score)
    keep = np.unique(np.linspace(0, len(fpr) - 1, min(n, len(fpr))).astype(int))
    return [{"fpr": r(fpr[i]), "tpr": r(tpr[i])} for i in keep]


# ------------------------------------------------------------------ Member 1: cost


def evaluate_cost():
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import LinearRegression
    from sklearn.pipeline import Pipeline
    from sklearn.base import clone

    df = pd.read_csv(ML / "cost" / "data" / "insurance.csv").drop_duplicates()
    X, y = df.drop(columns="expenses"), df["expenses"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = joblib.load(ML / "cost" / "models" / "cost_prediction_model.pkl")
    pred = model.predict(X_test)
    train_pred = model.predict(X_train)

    # the notebook compared four regressors before keeping Gradient Boosting; refit them the same way
    preprocessor = model.named_steps["preprocessor"]
    candidates = {
        "Linear Regression": LinearRegression(),
        "Random Forest": RandomForestRegressor(n_estimators=200, random_state=42),
        "Gradient Boosting": GradientBoostingRegressor(random_state=42),
    }
    try:
        from xgboost import XGBRegressor
        candidates["XGBoost"] = XGBRegressor(n_estimators=300, learning_rate=0.05, max_depth=5, random_state=42,
                                             objective="reg:squarederror")
    except ImportError:
        pass
    comparison = []
    for name, est in candidates.items():
        p = Pipeline([("preprocessor", clone(preprocessor)), ("model", est)]).fit(X_train, y_train).predict(X_test)
        comparison.append({"model": name, "r2": r(r2_score(y_test, p)), "mae_inr": r(mean_absolute_error(y_test, p) * USD_TO_INR, 0),
                           "rmse_inr": r(np.sqrt(mean_squared_error(y_test, p)) * USD_TO_INR, 0), "selected": name == "Gradient Boosting"})

    # accuracy by smoker: the biggest driver, so show where the model is weaker
    groups = []
    for label, mask in (("Non-smokers", X_test["smoker"] == "no"), ("Smokers", X_test["smoker"] == "yes")):
        groups.append({"group": label, "n": int(mask.sum()), "r2": r(r2_score(y_test[mask], pred[mask])),
                       "mae_inr": r(mean_absolute_error(y_test[mask], pred[mask]) * USD_TO_INR, 0)})

    gbr = model.named_steps["model"]
    names = [n.split("__", 1)[1] for n in preprocessor.get_feature_names_out()]
    importance = sorted(({"feature": n, "importance": r(v)} for n, v in zip(names, gbr.feature_importances_)),
                        key=lambda d: -d["importance"])

    within = np.abs(pred - y_test.values) / y_test.values
    return {
        "dataset": {"name": "Medical Cost Personal Dataset (insurance.csv)", "rows": int(len(df)),
                    "train": int(len(X_train)), "test": int(len(X_test)), "target": "Annual medical expenses",
                    "features": list(X.columns), "split": "80/20 random split, random_state=42 (Member 1's notebook)"},
        "metrics": {
            "r2": r(r2_score(y_test, pred)), "train_r2": r(r2_score(y_train, train_pred)),
            "mae_inr": r(mean_absolute_error(y_test, pred) * USD_TO_INR, 0),
            "rmse_inr": r(np.sqrt(mean_squared_error(y_test, pred)) * USD_TO_INR, 0),
            "mape_pct": r(np.mean(within) * 100, 1),
            "within_20_pct": r(np.mean(within <= 0.20) * 100, 1),
        },
        "comparison": comparison,
        "by_group": groups,
        "feature_importance": importance,
        "scatter": [{"actual": r(a * USD_TO_INR, 0), "predicted": r(p * USD_TO_INR, 0), "smoker": s == "yes"}
                    for a, p, s in zip(y_test.values, pred, X_test["smoker"].values)],
        "usd_to_inr": USD_TO_INR,
    }


# ------------------------------------------------------------------ Member 2: fraud


FRAUD_DROP = ["ClaimID", "PatientID", "ProviderID", "ClaimDate", "Cluster", "ClaimStatus", "ClaimLegitimacy",
              "DiagnosisCode", "ProcedureCode"]


def evaluate_fraud():
    from sklearn.base import clone

    models = ML / "fraud" / "models"
    df = pd.read_excel(ML / "fraud" / "data" / "Health Insurance Fraud Claims.xlsx")
    df["Fraud"] = (df["ClaimLegitimacy"] == "Fraud").astype(int)
    dates = pd.to_datetime(df["ClaimDate"])
    df["ClaimYear"], df["ClaimMonth"], df["ClaimDayOfWeek"] = dates.dt.year, dates.dt.month, dates.dt.dayofweek
    X, y = df.drop(columns=FRAUD_DROP + ["Fraud"]), df["Fraud"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.20, random_state=42, stratify=y)

    pre = joblib.load(models / "robust_preprocessor.pkl")
    xgb = joblib.load(models / "robust_xgboost_fraud.pkl")
    iso = joblib.load(models / "isolation_forest.pkl")
    scaler = joblib.load(models / "anomaly_scaler.pkl")
    threshold = float(joblib.load(models / "fraud_threshold.pkl"))

    Xt = pre.transform(X_test)
    prob = xgb.predict_proba(Xt)[:, 1]
    anomaly = np.clip(scaler.transform((-iso.decision_function(Xt)).reshape(-1, 1)).ravel(), 0, 1)
    hybrid = 0.80 * prob + 0.20 * anomaly

    # threshold choice, as in src/15_threshold_optimization.py: refit on 80% of the training rows,
    # score the other 20% (validation), pick the threshold with the best F1
    Xtr = pre.transform(X_train)
    Xa, Xv, ya, yv = train_test_split(Xtr, y_train, test_size=0.20, random_state=42, stratify=y_train)
    pv = clone(xgb).fit(Xa, ya).predict_proba(Xv)[:, 1]
    sweep = []
    for t in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70, 0.80, 0.90]:
        pred_v, pred_t = (pv >= t).astype(int), (prob >= t).astype(int)
        sweep.append({"threshold": t,
                      "val_precision": r(precision_score(yv, pred_v, zero_division=0)), "val_recall": r(recall_score(yv, pred_v, zero_division=0)),
                      "val_f1": r(f1_score(yv, pred_v, zero_division=0)),
                      "test_fp": int(((pred_t == 1) & (y_test.values == 0)).sum()), "test_fn": int(((pred_t == 0) & (y_test.values == 1)).sum())})

    # risk bands of the hybrid score on the test claims
    bands = []
    for level, lo, hi in (("LOW", 0, 0.40), ("MEDIUM", 0.40, 0.70), ("HIGH", 0.70, 1.01)):
        m = (hybrid >= lo) & (hybrid < hi)
        bands.append({"level": level, "claims": int(m.sum()), "fraud": int(y_test.values[m].sum()),
                      "fraud_rate": r(y_test.values[m].mean() if m.any() else 0)})

    # why the scores are so high: in this dataset the label follows claim amount and income almost exactly
    amt_min = float(df.loc[df.Fraud == 1, "ClaimAmount"].min())
    inc_max = float(df.loc[df.Fraud == 1, "PatientIncome"].max())
    rule = ((X_test["ClaimAmount"] >= amt_min) & (X_test["PatientIncome"] <= inc_max)).astype(int)

    # 5-fold cross-validation of the same model on the whole dataset: is the test result a lucky split?
    from sklearn.model_selection import StratifiedKFold
    from sklearn.pipeline import Pipeline
    cv = []
    for tr, te in StratifiedKFold(n_splits=5, shuffle=True, random_state=42).split(X, y):
        pipe = Pipeline([("pre", clone(pre)), ("m", clone(xgb))]).fit(X.iloc[tr], y.iloc[tr])
        p = pipe.predict_proba(X.iloc[te])[:, 1]
        cv.append({"roc_auc": r(roc_auc_score(y.iloc[te], p)), "f1": r(f1_score(y.iloc[te], (p >= threshold).astype(int)))})

    imp = xgb.feature_importances_
    names = [n.split("__", 1)[1] for n in pre.get_feature_names_out()]
    importance = sorted(({"feature": n, "importance": r(v)} for n, v in zip(names, imp) if v > 0), key=lambda d: -d["importance"])[:10]

    sample = X_test.assign(Fraud=y_test.values)
    sample = pd.concat([sample[sample.Fraud == 1], sample[sample.Fraud == 0].sample(300, random_state=1)])
    return {
        "dataset": {"name": "Health Insurance Fraud Claims (Kaggle)", "rows": int(len(df)), "fraud": int(y.sum()),
                    "fraud_pct": r(y.mean() * 100, 1), "train": int(len(X_train)), "test": int(len(X_test)),
                    "test_fraud": int(y_test.sum()),
                    "split": "Stratified 80/20 split, random_state=42 (src/11_robust_preprocess.py)",
                    "removed": "IDs, ClaimStatus, Cluster (leak the answer); DiagnosisCode, ProcedureCode (codes with 100% fraud rate)"},
        "threshold": threshold,
        "xgboost": {**binary_metrics(y_test.values, (prob >= threshold).astype(int), prob), "roc": roc_points(y_test.values, prob)},
        "xgboost_at_050": binary_metrics(y_test.values, (prob >= 0.5).astype(int)),
        "isolation_forest": {**binary_metrics(y_test.values, (iso.predict(Xt) == -1).astype(int), anomaly),
                             "roc": roc_points(y_test.values, anomaly)},
        "hybrid": {**binary_metrics(y_test.values, (hybrid >= 0.40).astype(int), hybrid), "roc": roc_points(y_test.values, hybrid),
                   "bands": bands},
        "threshold_sweep": sweep,
        "cross_validation": {"folds": cv, "roc_auc_mean": r(np.mean([c["roc_auc"] for c in cv])),
                             "f1_mean": r(np.mean([c["f1"] for c in cv])), "f1_std": r(np.std([c["f1"] for c in cv]))},
        "simple_rule": {"claim_amount_min_usd": r(amt_min, 2), "income_max_usd": r(inc_max, 2),
                        **binary_metrics(y_test.values, rule.values)},
        "feature_importance": importance,
        "scatter": [{"amount_inr": r(a * USD_TO_INR, 0), "income_inr": r(i * USD_TO_INR, 0), "fraud": bool(f)}
                    for a, i, f in zip(sample.ClaimAmount, sample.PatientIncome, sample.Fraud)],
    }


# ------------------------------------------------------------------ Member 3: bill models + OCR


def evaluate_bill_models():
    sys.path.insert(0, str(ML / "bill" / "bill_app" / "ml"))
    import generate_pricing_dataset as gen

    bundle = joblib.load(ML / "bill" / "bill_app" / "ml" / "fair_price_model.pkl")
    pipe = bundle["pipeline"]
    feats = bundle["categorical_features"] + bundle["numeric_features"]

    # the same 6,000 rows and 80/20 split as train_fair_price_model.py
    gen.np.random.seed(42)
    df = gen.generate_pricing_dataset(n_samples=6000)
    X_train, X_test, y_train, y_test = train_test_split(df[feats], df["fair_price"], test_size=0.2, random_state=42)
    pred = pipe.predict(X_test)
    by_cat = []
    for cat in sorted(X_test["category"].unique()):
        m = (X_test["category"] == cat).values
        by_cat.append({"category": cat, "n": int(m.sum()), "mape_pct": r(np.mean(np.abs(pred[m] - y_test.values[m]) / y_test.values[m]) * 100, 1),
                       "mae_inr": r(mean_absolute_error(y_test.values[m], pred[m]), 0)})
    fair = {
        "dataset": {"name": "Synthetic Indian hospital tariffs (generate_pricing_dataset.py)", "rows": 6000,
                    "train": int(len(X_train)), "test": int(len(X_test)), "features": feats,
                    "split": "80/20 random split, random_state=42 (train_fair_price_model.py)"},
        "metrics": {"r2": r(r2_score(y_test, pred)), "mae_inr": r(mean_absolute_error(y_test, pred), 0),
                    "mape_pct": r(np.mean(np.abs(pred - y_test.values) / y_test.values) * 100, 1),
                    "noise_floor_pct": 14.4},  # the generator multiplies every price by N(1, 0.18): mean |error| ~ 0.8 x 18%
        "by_category": by_cat,
        "importance": [{"feature": d["feature"], "importance": r(d["importance"])} for d in bundle["feature_importance"][:8]],
    }

    # anomaly model on a fresh batch: different seed, so none of these rows were used for training
    an = joblib.load(ML / "bill" / "bill_app" / "ml" / "lineitem_anomaly_model.pkl")
    gen.np.random.seed(2026)
    rng = np.random.default_rng(2026)
    fresh = gen.generate_pricing_dataset(n_samples=3000)
    fresh["fair_price_predicted"] = pipe.predict(fresh[feats])
    n_bad = int(len(fresh) * 0.06)
    bad = np.zeros(len(fresh), bool)
    bad[rng.choice(len(fresh), n_bad, replace=False)] = True
    mult = np.where(bad, rng.uniform(2.0, 6.0, len(fresh)), rng.normal(1.0, 0.15, len(fresh)))
    fresh["billed_amount"] = (fresh["fair_price_predicted"] * mult).round(2)
    fresh["overcharge_ratio"] = (fresh["billed_amount"] / fresh["fair_price_predicted"]).round(3)
    Xa = np.hstack([an["encoder"].transform(fresh[an["categorical_features"]]).toarray(),
                    an["scaler"].transform(fresh[an["numeric_features"]].values)])
    flagged = (an["model"].predict(Xa) == -1).astype(int)
    score = -an["model"].decision_function(Xa)
    # the app's own severity rule (ml_bill_scorer.py): "review" if the anomaly model flags the line or it is
    # 25%+ above fair price; "high risk" only if the model flags it AND it is 60%+ above fair price
    pct = (fresh["overcharge_ratio"].values - 1) * 100
    review_or_high = ((flagged == 1) | (pct >= 25)).astype(int)
    high_risk = ((flagged == 1) & (pct >= 60)).astype(int)
    anomaly = {
        "dataset": {"name": "Fresh synthetic line items (seed 2026), 6% overcharged 2x-6x", "rows": len(fresh),
                    "overcharged": int(bad.sum()),
                    "note": "Member 3's script scored the rows it trained on; this batch is new, so the model has not seen it."},
        "isolation_forest": {**binary_metrics(bad.astype(int), flagged, score), "roc": roc_points(bad.astype(int), score)},
        "app_flagged": binary_metrics(bad.astype(int), review_or_high),
        "app_high_risk": binary_metrics(bad.astype(int), high_risk),
    }
    return {"fair_price": fair, "anomaly": anomaly}


def _norm(s):
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def evaluate_ocr():
    """Reads every sample bill and compares what OCR + parser found with what is printed on it."""
    sys.path.insert(0, str(SAMPLES))
    from app.services.ml import registry
    from app.services.verification import bill_number_key, name_similarity
    import make_samples as ms

    registry.load()
    bill = registry.bill
    specs = {**ms.BILLS, **{f"new_bills/{k}": v for k, v in ms.NEW_BILLS.items()},
             **{f"ramesh_bills/{k}": v for k, v in ms.RAMESH_BILLS.items()}}
    rows = []
    for name, spec in specs.items():
        path = SAMPLES / name
        if not path.exists():
            continue
        t0 = time.time()
        parsed = bill.parse(bill.ocr(str(path)))
        secs = time.time() - t0
        printed = {round(a, 2) for _, a in spec["items"]}
        read = [round(float(i["amount"]), 2) for i in parsed["line_items"]]
        amounts_ok = sum(1 for a in read if a in printed)
        total = spec.get("stated_total", sum(a for _, a in spec["items"]))
        rows.append({
            "file": name, "lines_printed": len(spec["items"]), "lines_read": len(read),
            "amounts_correct": min(amounts_ok, len(spec["items"])),
            "bill_number": bill_number_key(parsed.get("bill_number") or "") == bill_number_key(spec["bill_no"]),
            "patient_name": name_similarity(parsed.get("patient_name") or "", spec["patient"]) >= 0.85,
            "hospital_name": name_similarity(parsed.get("hospital_name") or "", spec["hospital"]) >= 0.85,
            "total": parsed.get("stated_total") is not None and abs(float(parsed["stated_total"]) - total) < 1,
            "dates": bool(parsed.get("admission_date")) and bool(parsed.get("discharge_date")),
            "seconds": r(secs, 1),
        })
    n = len(rows)
    lines = sum(x["lines_printed"] for x in rows)
    fields = {k: sum(1 for x in rows if x[k]) for k in ("bill_number", "patient_name", "hospital_name", "total", "dates")}
    return {
        "bills": n, "lines_printed": lines, "amounts_correct": sum(x["amounts_correct"] for x in rows),
        "line_accuracy": r(sum(x["amounts_correct"] for x in rows) / lines),
        "fields": fields, "avg_seconds": r(np.mean([x["seconds"] for x in rows]), 1), "rows": rows,
        "note": "Clean, printed sample bills. Phone photos with shadows, folds or tilt will read less well.",
    }


# ------------------------------------------------------------------ Member 4: authenticity


AUTH_CASES = [
    # (file, patient email, hospital email, genuine?, what it is)
    ("patient_copies/copy_01_genuine_priya_citycare.png", "priya", "citycare", True, "Genuine copy of a City Care bill"),
    ("ramesh_bills/ramesh_03_kidney_stone_citycare.png", "ramesh", "citycare", True, "Genuine copy, hospital record on file"),
    ("ramesh_bills/ramesh_04_typhoid_sunrise.png", "ramesh", "sunrise", True, "Genuine copy, hospital record on file"),
    ("ramesh_bills/ramesh_05_pneumonia_citycare.png", "ramesh", "citycare", True, "Genuine copy, hospital record on file"),
    ("ramesh_bills/ramesh_06_cataract_daycare_sunrise.png", "ramesh", "sunrise", True, "Genuine copy, hospital record on file"),
    ("new_bills/new_bill_01_maternity_citycare.png", "priya", "citycare", True, "Genuine bill, no hospital record yet"),
    ("new_bills/new_bill_02_dengue_sunrise.png", "ramesh", "sunrise", True, "Genuine bill, no hospital record yet"),
    ("new_bills/new_bill_03_fracture_sunrise.png", "arjun", "sunrise", True, "Genuine bill, no hospital record yet"),
    ("new_bills/new_bill_04_ent_no_insurance_citycare.png", "meena", "citycare", True, "Genuine bill, no hospital record yet"),
    ("new_bills/new_bill_07_appendix_citycare.pdf", "priya", "citycare", True, "Genuine PDF bill, no hospital record yet"),
    ("fake_bills/fake_01_wrong_hospital.png", "priya", "citycare", False, "Another hospital's bill"),
    ("fake_bills/fake_02_wrong_patient.png", "priya", "citycare", False, "Someone else's bill"),
    ("fake_bills/fake_03_reused_bill_number.png", "ramesh", "citycare", False, "Made-up bill reusing a real bill number"),
    ("fake_bills/fake_04_impossible_dates.png", "arjun", "sunrise", False, "Discharge before admission"),
    ("fake_bills/fake_05_photoshop_metadata.jpg", "priya", "citycare", False, "Saved by Photoshop"),
    ("fake_bills/fake_06_pasted_amount.jpg", "arjun", "sunrise", False, "Amount pasted over (₹36,000 → ₹86,000)"),
    ("fake_bills/fake_07_edited_pdf.pdf", "ramesh", "sunrise", False, "PDF re-saved by an editor"),
    ("new_bills/new_bill_01_maternity_citycare.png", "priya", "citycare", False, "Same bill submitted a second time"),
]
HOSPITAL_EMAIL = {"citycare": "citycare@hospital.in", "sunrise": "sunrise@hospital.in"}


def evaluate_authenticity():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.seed import seed

    rows = []
    with TestClient(app) as client:
        from app.database import SessionLocal
        with SessionLocal() as db:
            seed(db)

        def login(email):
            tok = client.post("/api/auth/login", json={"email": email, "password": "Demo@1234"}).json()["access_token"]
            return {"Authorization": f"Bearer {tok}"}

        hospitals = {}
        for key, email in HOSPITAL_EMAIL.items():
            hospitals[key] = client.get("/api/auth/me", headers=login(email)).json()["hospital"]["id"]

        for file, patient, hosp, genuine, what in AUTH_CASES:
            path = SAMPLES / file
            if not path.exists():
                continue
            with open(path, "rb") as fh:
                res = client.post("/api/bills/upload", headers=login(f"{patient}@patient.in"),
                                  data={"hospital_id": str(hospitals[hosp])}, files={"file": (path.name, fh)})
            if res.status_code == 422:
                outcome, failed, warned, status = "refused", [res.json().get("detail", "Upload refused")], [], "refused"
            elif res.status_code >= 300:
                outcome, failed, warned, status = "error", [res.text[:120]], [], "error"
            else:
                b = res.json()
                checks = b.get("checks") or []
                failed = [c["name"] for c in checks if c["status"] == "fail"]
                warned = [c["name"] for c in checks if c["status"] == "warn"]
                status = b.get("verification_status")
                outcome = ("blocked" if failed or status == "mismatch" else "warning" if warned else
                           "matched" if status == "matched" else "awaiting")
            flagged = outcome in ("refused", "blocked", "warning")
            rows.append({"file": file, "what": what, "genuine": genuine, "outcome": outcome, "status": status,
                         "failed": failed, "warned": warned, "correct": flagged != genuine})

    fakes = [x for x in rows if not x["genuine"]]
    real = [x for x in rows if x["genuine"]]
    tp = sum(1 for x in fakes if x["outcome"] != "awaiting" and x["outcome"] != "matched")
    fp = sum(1 for x in real if x["outcome"] in ("refused", "blocked", "warning"))
    return {
        "fakes": len(fakes), "fakes_caught": tp, "fakes_blocked": sum(1 for x in fakes if x["outcome"] in ("refused", "blocked")),
        "genuine": len(real), "genuine_flagged": fp,
        "genuine_matched": sum(1 for x in real if x["outcome"] == "matched"),
        "confusion": {"tp": tp, "fn": len(fakes) - tp, "fp": fp, "tn": len(real) - fp},
        "rows": rows,
        "note": "Hand-made test set: each fake targets one check. It shows the checks work as designed, "
                "not how often they would catch a determined forger in real life.",
    }


# ------------------------------------------------------------------ treatment cost estimate


TIERS = ["tier3", "tier2", "metro"]
TYPES = ["government", "private", "multispeciality", "premium"]


def evaluate_treatment():
    """Not a trained model, so no accuracy score: checks that the calculation behaves as designed,
    and the same treatment priced across every hospital type and city."""
    import app.services.ml  # noqa: F401  (puts Member 3's module on the path)
    from app.services import treatment_cost as tc

    def total(key, tier, typ, **kw):
        return tc.estimate(key, tier, typ, **kw)["total"]

    keys = [t.key for t in tc.TREATMENTS]
    checks = []

    def check(name, results, detail):
        checks.append({"name": name, "passed": sum(results), "total": len(results), "detail": detail})

    standard = [tc.estimate(t.key, "tier3", "private") for t in tc.TREATMENTS]
    check("Reproduces the official package rate",
          [r["total"] == (t.package or tc.WARD_PER_DAY * t.los) + t.implant for r, t in zip(standard, tc.TREATMENTS)],
          "Private hospital, tier-3 city, standard stay: the estimate equals the HBP 2022 package (+ implant).")
    check("Steps add up to the total",
          [sum(s["amount"] for s in r["steps"]) == r["total"]
           for k in keys for r in [tc.estimate(k, "metro", "premium", icu_days=1, room="private", emergency=True,
                                               conditions=("diabetes", "heart_disease"), age=65)]],
          "Every rupee of the total is explained by one listed step.")
    check("Government hospital cheapest",
          [total(k, tier, "government") < min(total(k, tier, t) for t in TYPES[1:]) for k in keys for tier in TIERS],
          "In every city, for every treatment.")
    check("Bigger city costs more",
          [total(k, "tier3", typ) < total(k, "tier2", typ) < total(k, "metro", typ) for k in keys for typ in TYPES],
          "Tier-3 < tier-2 < metro, for every treatment and hospital type.")
    extras = {"ICU day": dict(icu_days=1), "private room": dict(room="private"), "emergency": dict(emergency=True),
              "diabetes": dict(conditions=("diabetes",)), "age 60+": dict(age=65), "longer stay": dict(ward_days=10)}
    check("Each extra raises the price",
          [total(k, "tier2", "private", **kw) > total(k, "tier2", "private") for k in keys for kw in extras.values()],
          f"{', '.join(extras)}: each one alone, for every treatment.")

    grid_key = "appendix"
    grid = [{"hospital_type": typ, **{tier: total(grid_key, tier, typ) for tier in TIERS}} for typ in TYPES]
    return {
        "checks": checks,
        "grid": {"treatment": tc.BY_KEY[grid_key].name, "code": tc.BY_KEY[grid_key].code,
                 "package": tc.BY_KEY[grid_key].package, "rows": grid},
        "standard": [{"name": t.name, "code": t.code, "package": t.package or tc.WARD_PER_DAY * t.los, "implant": t.implant,
                      "metro_multispeciality": total(t.key, "metro", "multispeciality")} for t in tc.TREATMENTS],
        "range_pct": standard[0]["range_pct"],
    }


# ------------------------------------------------------------------ main


def main():
    started = time.time()
    sections = {"cost": evaluate_cost, "fraud": evaluate_fraud, "bill": evaluate_bill_models,
                "ocr": evaluate_ocr, "authenticity": evaluate_authenticity, "treatment": evaluate_treatment}
    only = sys.argv[1:]
    result = json.loads(OUT.read_text()) if only and OUT.exists() else {}
    for key, fn in sections.items():
        if only and key not in only:
            continue
        t0 = time.time()
        print(f"evaluating {key} ...", flush=True)
        result[key] = fn()
        print(f"  done in {time.time() - t0:.0f}s", flush=True)
    result["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT} in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
