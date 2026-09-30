"""End-to-end API tests on a throwaway SQLite database (real models, real pipeline)."""

import os
import tempfile

_db = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp()
os.environ["SEED_DEMO"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PASSWORD = "Secret@123"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def register(client, email, role, **extra):
    r = client.post("/api/auth/register", json={"email": email, "password": PASSWORD, "full_name": email.split("@")[0],
                                                "role": role, **extra})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]


@pytest.fixture(scope="module")
def actors(client):
    patient, patient_user = register(client, "pat@test.in", "patient")
    hospital, _ = register(client, "hosp@test.in", "hospital", organization_name="Test Hospital", city="Chennai",
                           city_tier="metro", hospital_type="multispeciality")
    insurer, _ = register(client, "ins@test.in", "insurer", organization_name="Test Insurer")
    return {"patient": patient, "patient_id": patient_user["id"], "hospital": hospital, "insurer": insurer}


def test_health_reports_all_models_loaded(client):
    body = client.get("/api/health").json()
    assert body["database"] == "ok"
    assert all(m["loaded"] for m in body["models"].values()), body


def test_auth_rules(client, actors):
    assert client.post("/api/auth/login", json={"email": "pat@test.in", "password": "wrong-pass"}).status_code == 401
    assert client.get("/api/dashboard/patient").status_code == 401
    assert client.get("/api/dashboard/insurer", headers=actors["patient"]).status_code == 403
    dup = client.post("/api/auth/register", json={"email": "pat@test.in", "password": PASSWORD,
                                                  "full_name": "x y", "role": "patient"})
    assert dup.status_code == 409
    # admin/finance accounts cannot be self-registered
    bad = client.post("/api/auth/register", json={"email": "a@test.in", "password": PASSWORD,
                                                  "full_name": "x y", "role": "admin"})
    assert bad.status_code == 422


def test_cost_prediction_member1(client, actors):
    profile = {"age": 45, "sex": "male", "bmi": 31.2, "children": 2, "smoker": "yes", "region": "southeast",
               "marital_status": "Married", "employment_status": "Employed", "monthly_income": 22000,
               "existing_monthly_debt": 3000, "has_credit_card": True}
    assert client.put("/api/patients/me/profile", json=profile, headers=actors["patient"]).status_code == 200
    r = client.post("/api/cost/estimate", json={}, headers=actors["patient"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["predicted_usd"] > 30000  # smoker with high BMI
    assert body["shap"][0]["feature"] == "smoker"
    shap_total = sum(s["shap_usd"] for s in body["shap"])
    assert 0 < shap_total < body["predicted_usd"]


def test_bill_claim_payment_flow(client, actors):
    # insurer issues the same policy Member 3's demo uses
    r = client.post("/api/policies", headers=actors["insurer"], json={
        "patient_email": "pat@test.in", "deductible": 5000, "co_insurance_pct": 20, "copay_flat": 500,
        "room_rent_cap": 20000, "sum_insured": 150000})
    assert r.status_code == 201, r.text

    # hospital runs Member 3's sample bill for the patient
    r = client.post("/api/bills/sample", data={"patient_id": actors["patient_id"]}, headers=actors["hospital"])
    assert r.status_code == 201, r.text
    bill = r.json()
    assert bill["total_billed"] == 126320.0
    assert bill["duplicate_count"] == 1 and bill["high_risk_count"] == 1
    assert bill["patient_out_of_pocket"] == 34964.0
    assert bill["insurance_pays"] + bill["patient_out_of_pocket"] == bill["total_billed"]  # copay fix
    ct = next(i for i in bill["items"] if i["description"] == "CT Scan Chest")
    assert ct["severity"] == "high_risk"
    assert bill["recommendations"][0]["option"] == "Hospital No-Cost EMI"

    # the patient sees it; another role without access does not
    assert client.get(f"/api/bills/{bill['id']}", headers=actors["patient"]).status_code == 200

    # hospital files the claim -> Member 2 scores it
    r = client.post("/api/claims", headers=actors["hospital"], json={
        "bill_id": bill["id"], "claim_type": "Inpatient", "provider_specialty": "General Practice"})
    assert r.status_code == 201, r.text
    claim = r.json()
    assert claim["risk_level"] in ("LOW", "MEDIUM", "HIGH")
    assert len(claim["top_factors"]) == 5
    assert claim["claim_amount"] == bill["insurance_pays"]
    # Claim Decision Engine: drop the duplicate paracetamol, pay the CT scan only up to fair price + 25%
    advice = claim["advice"]
    assert advice["decision"] == "approve_reduced"
    assert {d["description"] for d in advice["bill_deductions"]} == {"Paracetamol 500mg x10 Tab", "CT Scan Chest"}
    assert 0 < advice["recommended_amount"] < claim["claim_amount"]
    assert advice["recommended_amount"] == 76718.81
    again = client.post("/api/claims", headers=actors["hospital"], json={
        "bill_id": bill["id"], "claim_type": "Inpatient", "provider_specialty": "General Practice"})
    assert again.status_code == 409

    # insurer approves, then settles; settling twice is refused
    r = client.post(f"/api/claims/{claim['id']}/decision", headers=actors["insurer"], json={"action": "approve"})
    assert r.json()["status"] == "approved"
    r = client.post(f"/api/claims/{claim['id']}/decision", headers=actors["insurer"], json={"action": "settle"})
    assert r.json()["status"] == "settled"
    assert client.post(f"/api/claims/{claim['id']}/decision", headers=actors["insurer"],
                       json={"action": "settle"}).status_code == 409
    assert client.post(f"/api/claims/{claim['id']}/decision", headers=actors["hospital"],
                       json={"action": "approve"}).status_code == 403

    # patient chooses a 12-month EMI at 13.5%
    r = client.post(f"/api/bills/{bill['id']}/pay", headers=actors["patient"],
                    json={"plan": "emi", "annual_rate": 13.5, "months": 12})
    assert r.status_code == 200, r.text
    assert r.json()["payment"]["monthly_emi"] == 3131.1
    assert r.json()["payment_status"] == "on_emi"


def test_manual_bill_without_policy_is_all_out_of_pocket(client, actors):
    patient2, _ = register(client, "pat2@test.in", "patient")
    hospitals = client.get("/api/hospitals", headers=patient2).json()
    r = client.post("/api/bills/manual", headers=patient2, json={
        "hospital_id": hospitals[0]["id"],
        "items": [{"description": "Consultation - Physician", "amount": 800},
                  {"description": "X-Ray Chest", "amount": 1400}]})
    assert r.status_code == 201, r.text
    bill = r.json()
    assert bill["insurance_pays"] == 0 and bill["patient_out_of_pocket"] == 2200
    # no insurance -> no claim possible
    r = client.post("/api/claims", headers=patient2, json={
        "bill_id": bill["id"], "claim_type": "Outpatient", "provider_specialty": "General Practice"})
    assert r.status_code == 422
    # the first patient cannot open someone else's bill
    assert client.get(f"/api/bills/{bill['id']}", headers=actors["patient"]).status_code == 404


def test_dashboards(client, actors):
    p = client.get("/api/dashboard/patient", headers=actors["patient"]).json()
    assert p["bills"]["count"] == 1 and p["active_policy"] is not None
    h = client.get("/api/dashboard/hospital", headers=actors["hospital"]).json()
    assert h["revenue"]["insurance_settled"] > 0
    i = client.get("/api/dashboard/insurer", headers=actors["insurer"]).json()
    assert i["claims"]["by_status"]["settled"] == 1 and i["provider_risk"]
    assert client.get("/api/dashboard/finance", headers=actors["insurer"]).status_code == 403
