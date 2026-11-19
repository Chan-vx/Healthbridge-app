"""End-to-end API tests on a throwaway SQLite database (real models, real pipeline)."""

import os
import tempfile

_db = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp()
os.environ["SEED_DEMO"] = "false"

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Policy, User  # noqa: E402

PASSWORD = "Secret@123"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def register(client, email, role, full_name=None, **extra):
    r = client.post("/api/auth/register", json={"email": email, "password": PASSWORD,
                                                "full_name": full_name or email.split("@")[0], "role": role, **extra})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]


def backdate_policies(email, days=400):
    """Policies issued in a test start today; the sample bills are dated earlier."""
    with SessionLocal() as db:
        patient = db.scalar(select(User).where(User.email == email))
        for p in db.scalars(select(Policy).where(Policy.patient_id == patient.id)):
            p.created_at = datetime.now(timezone.utc) - timedelta(days=days)
        db.commit()


# names match Member 3's sample bill (City Care, patient Ramesh Kumar), as for a genuine bill
@pytest.fixture(scope="module")
def actors(client):
    patient, patient_user = register(client, "pat@test.in", "patient", full_name="Ramesh Kumar")
    hospital, hospital_user = register(client, "hosp@test.in", "hospital",
                                       organization_name="City Care Multispeciality Hospital", city="Chennai",
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
    backdate_policies("pat@test.in")

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
    # a genuine bill from the hospital itself passes every authenticity check
    assert bill["verification_status"] == "hospital_uploaded"
    assert bill["authenticity"] == "pass", bill["checks"]
    # only the second paracetamol line is the duplicate
    assert [i["description"] for i in bill["items"] if i["duplicate_of"]] == ["Paracetamol 500mg x10 Tab"]

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
    history = client.get("/api/claims?status=approved,settled,rejected", headers=actors["insurer"]).json()
    assert [c["status"] for c in history] == ["settled"]  # the insurer's decided claims
    assert client.get("/api/claims?status=submitted,approved", headers=actors["insurer"]).json() == []
    assert client.get("/api/dashboard/finance", headers=actors["insurer"]).status_code == 403


# ---------------------------------------------------------------- bill authenticity

TEXT_BILL = """{hospital}
12 MG Road, Chennai - 600001
Patient: {patient}   Bill No: {number}
Admission Date: {admission} Discharge Date: {discharge}
ITEMIZED CHARGES
Description Amount (Rs.)
Room Rent (2 days)  {room:.2f}
Consultation - Physician  1000.00
X-Ray Chest  3300.00
TOTAL AMOUNT DUE: Rs. {total:.2f}
"""


def day(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%d-%b-%Y")


def text_bill(client, actors, number, room=10800.0, hospital="CITY CARE MULTISPECIALITY HOSPITAL",
              patient="Ramesh Kumar", admission=None, discharge=None):
    raw = TEXT_BILL.format(hospital=hospital, patient=patient, number=number, room=room, total=room + 4300,
                           admission=admission or day(20), discharge=discharge or day(18))
    r = client.post("/api/bills/text", headers=actors["hospital"],
                    json={"patient_id": actors["patient_id"], "raw_text": raw})
    assert r.status_code == 201, r.text
    return r.json()


def checks(bill):
    return {c["key"]: c["status"] for c in bill["checks"]}


def claim(client, headers, bill_id):
    return client.post("/api/claims", headers=headers, json={
        "bill_id": bill_id, "claim_type": "Inpatient", "provider_specialty": "General Practice"})


def test_genuine_bill_passes_and_reused_bills_cannot_be_claimed(client, actors):
    genuine = text_bill(client, actors, "CCH-T-001")
    assert genuine["authenticity"] == "pass", genuine["checks"]

    # same bill number at the same hospital, different amounts
    reused = text_bill(client, actors, "CCH-T-001", room=11200)
    assert checks(reused)["duplicate_bill_number"] == "fail"
    r = claim(client, actors["hospital"], reused["id"])
    assert r.status_code == 422 and "repeats an earlier one" in r.json()["detail"]

    # the genuine bill copied under a new number (same dates, lines and amounts)
    copied = text_bill(client, actors, "CCH-T-002")
    assert checks(copied)["duplicate_content"] == "fail"
    assert claim(client, actors["hospital"], copied["id"]).status_code == 422

    # Member 3's sample image submitted a second time
    second_sample = client.post("/api/bills/sample", data={"patient_id": actors["patient_id"]},
                               headers=actors["hospital"]).json()
    assert checks(second_sample)["duplicate_file"] == "fail"


def test_forged_details_fail_and_hold_the_claim(client, actors):
    # a bill printed for someone else is not saved to this patient at all
    raw = TEXT_BILL.format(hospital="CITY CARE MULTISPECIALITY HOSPITAL", patient="Rahul Verma", number="CCH-T-010",
                           room=9800, total=14100, admission=day(20), discharge=day(18))
    count = len(client.get("/api/bills", headers=actors["hospital"]).json())
    r = client.post("/api/bills/text", headers=actors["hospital"], json={"patient_id": actors["patient_id"], "raw_text": raw})
    assert r.status_code == 422 and "Rahul Verma" in r.json()["detail"] and "Choose the patient" in r.json()["detail"]
    hospital_id = next(h["id"] for h in client.get("/api/hospitals", headers=actors["patient"]).json()
                       if h["name"] == "City Care Multispeciality Hospital")
    r = client.post("/api/bills/text", headers=actors["patient"], json={"hospital_id": hospital_id, "raw_text": raw})
    assert r.status_code == 422 and "only add bills issued to you" in r.json()["detail"]
    assert len(client.get("/api/bills", headers=actors["hospital"]).json()) == count  # nothing saved

    # a small OCR misreading of the name is only a warning; the bill is kept, and a failed check holds the claim
    misread = text_bill(client, actors, "CCH-T-011", room=9700, patient="Ramesh Kumor", hospital="GREENLEAF MEDICAL CENTRE")
    assert checks(misread)["patient_name"] == "pass" and checks(misread)["hospital_name"] == "fail"
    r = claim(client, actors["hospital"], misread["id"])
    assert r.status_code == 201, r.text
    assert r.json()["advice"]["decision"] == "investigate"

    wrong_hospital = text_bill(client, actors, "GMC-T-011", room=9900, hospital="GREENLEAF MEDICAL CENTRE")
    assert checks(wrong_hospital)["hospital_name"] == "fail"

    backwards = text_bill(client, actors, "CCH-T-012", room=10100, admission=day(10), discharge=day(14))
    assert checks(backwards)["dates"] == "fail"
    future = text_bill(client, actors, "CCH-T-013", room=10200, admission=day(-3), discharge=day(-1))
    assert checks(future)["dates"] == "fail"
    before_policy = text_bill(client, actors, "CCH-T-014", room=10300, admission=day(500), discharge=day(498))
    assert checks(before_policy)["dates"] == "warn"


def test_patient_upload_needs_hospital_confirmation(client, actors):
    hospital_id = next(h["id"] for h in client.get("/api/hospitals", headers=actors["patient"]).json()
                       if h["name"] == "City Care Multispeciality Hospital")
    items = [{"description": "Room Rent (3 days)", "amount": 15000},
             {"description": "Consultation - Orthopedic", "amount": 1000},
             {"description": "MRI Scan Knee", "amount": 3500}]

    def upload(rows, hospital=hospital_id):
        r = client.post("/api/bills/manual", headers=actors["patient"], json={"hospital_id": hospital, "items": rows})
        assert r.status_code == 201, r.text
        return r.json()

    bill = upload(items)
    assert bill["verification_status"] == "pending"
    r = claim(client, actors["patient"], bill["id"])
    assert r.status_code == 422 and "not confirmed" in r.json()["detail"]
    # only the hospital decides, and a dispute needs a reason
    url = f"/api/bills/{bill['id']}/verification"
    assert client.post(url, headers=actors["patient"], json={"action": "confirm"}).status_code == 403
    assert client.post(url, headers=actors["hospital"], json={"action": "dispute"}).status_code == 422
    confirmed = client.post(url, headers=actors["hospital"], json={"action": "confirm"})
    assert confirmed.json()["verification_status"] == "confirmed"
    assert client.post(url, headers=actors["hospital"], json={"action": "dispute", "note": "x"}).status_code == 409
    assert claim(client, actors["patient"], bill["id"]).status_code == 201

    other = upload([{**i, "amount": i["amount"] + 100} for i in items])
    client.post(f"/api/bills/{other['id']}/verification", headers=actors["hospital"],
                json={"action": "dispute", "note": "No such admission in our records."})
    r = claim(client, actors["patient"], other["id"])
    assert r.status_code == 422 and "disputed" in r.json()["detail"]

    assert upload(items, hospital=None)["verification_status"] == "unverifiable"
    hosp = client.get("/api/dashboard/hospital", headers=actors["hospital"]).json()
    assert all(b["verification_status"] in ("hospital_uploaded", "confirmed") for b in hosp["unclaimed_bills"])


def test_tampering_signals(tmp_path):
    from PIL import Image, ImageDraw

    from app.services.verification import error_level_image, name_similarity, tampering_signals

    assert name_similarity("CITY CARE MULTISPECIALITY HOSPITAL", "City Care Multispeciality Hospital") == 1.0
    assert name_similarity("R. Kumar", "Ramesh Kumar") >= 0.85
    assert name_similarity("Rahul Verma", "Ramesh Kumar") < 0.6

    img = Image.new("RGB", (600, 400), "white")
    ImageDraw.Draw(img).text((40, 40), "Room Rent (2 days)   6200.00", fill="black")
    clean = tmp_path / "clean.png"
    img.save(clean)
    assert tampering_signals(str(clean)) == []

    exif = Image.Exif()
    exif[305] = "Adobe Photoshop 25.0 (Windows)"
    edited = tmp_path / "edited.jpg"
    img.save(edited, "JPEG", quality=92, exif=exif)
    assert any("Photoshop" in s for s in tampering_signals(str(edited)))
    assert error_level_image(str(edited))[1:4] == b"PNG" and error_level_image(str(clean)) is None

    pdf = tmp_path / "edited.pdf"
    img.save(pdf, "PDF", creator="iLovePDF", creationDate=datetime(2026, 9, 1).timetuple(),
             modDate=datetime(2026, 9, 20).timetuple())
    signals = tampering_signals(str(pdf))
    assert any("iLovePDF" in s for s in signals) and any("modified after" in s for s in signals)


def test_patient_copy_is_compared_with_the_hospitals_record(client, actors):
    hospital_id = next(h["id"] for h in client.get("/api/hospitals", headers=actors["patient"]).json()
                       if h["name"] == "City Care Multispeciality Hospital")

    def raw(number, room=10800.0):
        return TEXT_BILL.format(hospital="CITY CARE MULTISPECIALITY HOSPITAL", patient="Ramesh Kumar", number=number,
                                room=room, total=room + 4300, admission=day(30), discharge=day(28))

    def patient_copy(text, headers=None):
        r = client.post("/api/bills/text", headers=headers or actors["patient"],
                        json={"hospital_id": hospital_id, "raw_text": text})
        assert r.status_code == 201, r.text
        return r.json()

    billed_before = client.get("/api/dashboard/patient", headers=actors["patient"]).json()["bills"]["total_billed"]
    record = text_bill(client, actors, "CCH-T-100", admission=day(30), discharge=day(28))

    # the same bill: matched to the hospital's record, not counted or claimed twice
    copy = patient_copy(raw("CCH-T-100"))
    assert copy["verification_status"] == "matched" and copy["matched_bill_id"] == record["id"]
    assert checks(copy)["hospital_record"] == "pass" and copy["authenticity"] == "pass", copy["checks"]
    r = claim(client, actors["patient"], copy["id"])
    assert r.status_code == 201 and r.json()["bill_id"] == record["id"], r.text  # filed on the hospital's record
    assert client.get(f"/api/bills/{copy['id']}", headers=actors["patient"]).json()["claim_status"] == "submitted"
    assert claim(client, actors["patient"], record["id"]).status_code == 409  # one claim per bill
    billed_after = client.get("/api/dashboard/patient", headers=actors["patient"]).json()["bills"]["total_billed"]
    assert billed_after == round(billed_before + record["total_billed"], 2)

    # an altered copy (room rent raised) is caught line by line, even with the number misread by OCR
    altered = patient_copy(raw("CCH-T-1OO", room=18800))
    assert altered["verification_status"] == "mismatch" and checks(altered)["hospital_record"] == "fail"
    diffs = {(d["kind"], d["description"]): (d["copy"], d["record"]) for d in altered["match_result"]["differences"]}
    assert diffs[("amount", "Room Rent (2 days)")] == (18800.0, 10800.0)
    assert ("total", "Total of the lines") in diffs
    assert claim(client, actors["patient"], altered["id"]).status_code == 422

    # another patient's bill number: refused without showing that bill
    other, _ = register(client, "pat3@test.in", "patient", full_name="Ramesh Kumar")
    r = client.post("/api/bills/text", headers=other, json={"hospital_id": hospital_id, "raw_text": raw("CCH-T-100")})
    assert r.status_code == 422 and "different patient" in r.json()["detail"]
    assert client.get("/api/bills", headers=other).json() == []

    # the patient uploads first; the hospital's record arrives later and settles it
    early = patient_copy(raw("CCH-T-200", room=10600))
    assert early["verification_status"] == "pending" and checks(early)["hospital_record"] == "waiting"
    late = text_bill(client, actors, "CCH-T-200", room=10600, admission=day(30), discharge=day(28))
    assert late["authenticity"] == "pass", late["checks"]  # the waiting copy is not a "repeat" of the record
    early = client.get(f"/api/bills/{early['id']}", headers=actors["patient"]).json()
    assert early["verification_status"] == "matched" and checks(early)["hospital_record"] == "pass"


def test_hospital_only_record_is_hidden_until_the_patient_uploads_a_matching_copy(client, actors):
    hospital_id = next(h["id"] for h in client.get("/api/hospitals", headers=actors["patient"]).json()
                       if h["name"] == "City Care Multispeciality Hospital")

    def raw(room):
        return TEXT_BILL.format(hospital="CITY CARE MULTISPECIALITY HOSPITAL", patient="Ramesh Kumar", number="CCH-T-300",
                                room=room, total=room + 4300, admission=day(40), discharge=day(38))

    r = client.post("/api/bills/text", headers=actors["hospital"],
                    json={"patient_id": actors["patient_id"], "raw_text": raw(10400), "record_only": True})
    assert r.status_code == 201, r.text
    record = r.json()
    assert record["record_only"] is True
    seen = lambda who: {b["id"] for b in client.get("/api/bills", headers=actors[who]).json()}  # noqa: E731
    assert record["id"] in seen("hospital")
    assert record["id"] not in seen("patient") and record["id"] not in seen("insurer")
    assert client.get(f"/api/bills/{record['id']}", headers=actors["patient"]).status_code == 404

    # an altered copy does not reveal the record
    altered = client.post("/api/bills/text", headers=actors["patient"], json={"hospital_id": hospital_id, "raw_text": raw(14400)})
    assert altered.json()["verification_status"] == "mismatch"
    assert record["id"] not in seen("patient")

    # the genuine copy matches, and the hospital's record appears in the patient's account
    copy = client.post("/api/bills/text", headers=actors["patient"], json={"hospital_id": hospital_id, "raw_text": raw(10400)})
    assert copy.json()["verification_status"] == "matched" and copy.json()["matched_bill_id"] == record["id"]
    assert record["id"] in seen("patient") and record["id"] in seen("insurer")
    assert claim(client, actors["patient"], record["id"]).status_code == 201


def test_bill_numbers_match_only_the_same_number():
    from app.services.verification import numbers_match
    assert numbers_match("CCH-2026-02011", "cch 2026 02011")
    assert numbers_match("CCH-2O26-O2O11", "CCH-2026-02011")  # OCR read 0 as O
    assert not numbers_match("CCH-2026-02011", "CCH-2026-02411")  # one digit apart: another patient's bill


def test_treatment_cost_estimate(client, actors):
    catalogue = client.get("/api/cost/treatments", headers=actors["patient"]).json()
    assert any(t["key"] == "knee" and t["package"] == 36400 for t in catalogue["treatments"])

    def estimate(**body):
        r = client.post("/api/cost/treatment", headers=actors["patient"],
                        json={"treatment": "appendix", "city_tier": "tier3", "hospital_type": "private", **body})
        assert r.status_code == 200, r.text
        return r.json()

    base = estimate()
    assert base["steps"][0]["amount"] == 21700  # the package rate itself at a tier-3 private hospital
    assert base["low"] < base["total"] < base["high"]
    assert sum(s["amount"] for s in base["steps"]) == base["total"]
    # each factor only adds: bigger city, ICU, private room, emergency, illnesses
    worse = estimate(city_tier="metro", icu_days=1, room="private", emergency=True, conditions=["diabetes"])
    assert worse["total"] > base["total"]
    assert {"City", "ICU", "Room category", "Emergency admission", "Diabetes"} <= {s["factor"] for s in worse["steps"]}
    assert estimate(hospital_type="government")["total"] < base["total"]
    knee = estimate(treatment="knee")
    assert any(s["factor"] == "Implant" and s["amount"] == 60500 for s in knee["steps"])
    assert client.post("/api/cost/treatment", headers=actors["patient"],
                       json={"treatment": "nose-job", "city_tier": "metro", "hospital_type": "private"}).status_code == 422


def test_sum_insured_is_a_yearly_limit(client, actors):
    patient, patient_user = register(client, "kiran@test.in", "patient", full_name="Kiran Rao")
    r = client.post("/api/policies", headers=actors["insurer"], json={
        "patient_email": "kiran@test.in", "deductible": 0, "co_insurance_pct": 0, "copay_flat": 0, "sum_insured": 100000})
    assert r.status_code == 201, r.text
    backdate_policies("kiran@test.in", days=30)

    def hospital_bill(number, surgery):
        r = client.post("/api/bills/manual", headers=actors["hospital"], json={
            "patient_id": patient_user["id"], "bill_number": number,
            "items": [{"description": "Surgery - Hernia Repair", "amount": surgery},
                      {"description": "Consultation - Surgeon", "amount": 1000}]})
        assert r.status_code == 201, r.text
        return r.json()

    def claim(bill_id):
        r = client.post("/api/claims", headers=actors["hospital"], json={
            "bill_id": bill_id, "claim_type": "Inpatient", "provider_specialty": "General Practice"})
        assert r.status_code == 201, r.text
        return r.json()

    first = claim(hospital_bill("SI-001", 59000)["id"])
    assert first["claim_amount"] == 60000
    assert first["coverage"]["left"] == 100000  # this claim itself not counted
    me = client.get("/api/policies/me", headers=patient).json()["coverage"]
    assert (me["pending"], me["left"]) == (60000, 40000)  # submitted claims hold their amount

    # the next bill is split with only what is left of the year's sum insured
    second = hospital_bill("SI-002", 69000)
    assert second["insurance_pays"] == 40000 and second["patient_out_of_pocket"] == 30000
    assert second["cost_breakdown"]["sum_insured_shortfall"] == 30000  # shown on its own line, not as co-insurance
    second_claim = claim(second["id"])
    assert second_claim["claim_amount"] == 40000

    # approving the first in full leaves nothing; the insurer cannot approve beyond the limit
    assert client.post(f"/api/claims/{first['id']}/decision", headers=actors["insurer"],
                       json={"action": "approve"}).json()["status"] == "approved"
    me = client.get("/api/policies/me", headers=patient).json()["coverage"]
    assert (me["used"], me["pending"], me["left"]) == (60000, 40000, 0)
    r = client.post(f"/api/claims/{second_claim['id']}/decision", headers=actors["insurer"], json={"action": "approve"})
    assert r.status_code == 200  # 40,000 was held for it, so it still fits
    # a third bill finds the sum insured used up
    third = hospital_bill("SI-003", 9000)
    assert third["insurance_pays"] == 0 and third["patient_out_of_pocket"] == 10000


def test_clear_my_records(client, actors):
    login = client.post("/api/auth/login", json={"email": "kiran@test.in", "password": PASSWORD}).json()
    kiran = {"Authorization": f"Bearer {login['access_token']}"}
    before = client.get("/api/account/records", headers=kiran).json()["counts"]
    assert before["bills"] == 3 and before["claims"] == 2  # from the sum insured test

    r = client.post("/api/account/records/clear", headers=kiran, json={"action": "delete"})
    assert r.status_code == 200 and r.json()["removed"] == before
    assert all(v == 0 for v in client.get("/api/account/records", headers=kiran).json()["counts"].values())
    hospital_bills = client.get("/api/bills", headers=actors["hospital"]).json()
    assert not any((b["bill_number"] or "").startswith("SI-") for b in hospital_bills)  # gone for the hospital too
    assert client.get("/api/policies/me", headers=kiran).json()["policy"] is not None  # the policy is kept

    # Kiran is not in the demo data, so a reset puts nothing back
    r = client.post("/api/account/records/clear", headers=kiran, json={"action": "reset"})
    assert r.status_code == 200 and r.json()["restored"]["bills"] == 0
    assert client.post("/api/account/records/clear", json={"action": "delete"}).status_code == 401


def test_patient_deletes_a_bill_from_their_account_only(client, actors):
    hospital_id = next(h["id"] for h in client.get("/api/hospitals", headers=actors["patient"]).json()
                       if h["name"] == "City Care Multispeciality Hospital")
    rows = [{"description": "Consultation - ENT", "amount": 900}, {"description": "Audiometry Test", "amount": 1400},
            {"description": "Tablet Cetirizine 10mg", "amount": 120}]
    bill = client.post("/api/bills/manual", headers=actors["patient"], json={"hospital_id": hospital_id, "items": rows}).json()

    def listed(headers):
        return any(b["id"] == bill["id"] for b in client.get("/api/bills", headers=headers).json())

    assert client.delete(f"/api/bills/{bill['id']}", headers=actors["hospital"]).status_code == 403  # patients only
    assert client.delete(f"/api/bills/{bill['id']}", headers=actors["patient"]).status_code == 204
    assert not listed(actors["patient"])
    assert client.get(f"/api/bills/{bill['id']}", headers=actors["patient"]).status_code == 404
    assert listed(actors["hospital"])  # the hospital keeps it, still waiting for confirmation
    assert client.get(f"/api/bills/{bill['id']}", headers=actors["hospital"]).json()["verification_status"] == "pending"
    # uploading the same bill again is not treated as a repeat of the deleted copy
    again = client.post("/api/bills/manual", headers=actors["patient"], json={"hospital_id": hospital_id, "items": rows}).json()
    assert all(c["status"] != "fail" for c in again["checks"]), again["checks"]

    # a bill with an open claim cannot be deleted until the insurer settles or rejects it
    claimed = client.post("/api/bills/manual", headers=actors["hospital"], json={
        "patient_id": actors["patient_id"], "bill_number": "DEL-001",
        "items": [{"description": "Surgery - Tonsillectomy", "amount": 30000}, {"description": "Consultation - ENT", "amount": 900}]}).json()
    c = claim(client, actors["hospital"], claimed["id"])
    assert c.status_code == 201, c.text
    r = client.delete(f"/api/bills/{claimed['id']}", headers=actors["patient"])
    assert r.status_code == 409 and "still open" in r.json()["detail"]
    client.post(f"/api/claims/{c.json()['id']}/decision", headers=actors["insurer"], json={"action": "reject"})
    assert client.delete(f"/api/bills/{claimed['id']}", headers=actors["patient"]).status_code == 204


def test_bill_from_another_registered_hospital_is_refused(client, actors):
    register(client, "sunrise@test.in", "hospital", organization_name="Sunrise General Hospital", city="Coimbatore",
             city_tier="tier2", hospital_type="private")
    hospitals = {h["name"]: h["id"] for h in client.get("/api/hospitals", headers=actors["patient"]).json()}
    raw = TEXT_BILL.format(hospital="SUNRISE GENERAL HOSPITAL", patient="Ramesh Kumar", number="SGH-T-001",
                           room=9800, total=14100, admission=day(9), discharge=day(7))
    count = len(client.get("/api/bills", headers=actors["patient"]).json())
    # the patient chose City Care for a Sunrise bill: refused, and told which hospital to choose
    r = client.post("/api/bills/text", headers=actors["patient"],
                    json={"hospital_id": hospitals["City Care Multispeciality Hospital"], "raw_text": raw})
    assert r.status_code == 422, r.text
    assert "Choose Sunrise General Hospital" in r.json()["detail"]
    assert len(client.get("/api/bills", headers=actors["patient"]).json()) == count  # nothing saved
    # a hospital cannot add another hospital's bill either
    r = client.post("/api/bills/text", headers=actors["hospital"], json={"patient_id": actors["patient_id"], "raw_text": raw})
    assert r.status_code == 422 and "can only add its own bills" in r.json()["detail"]
    # filed under the right hospital, it is accepted
    r = client.post("/api/bills/text", headers=actors["patient"],
                    json={"hospital_id": hospitals["Sunrise General Hospital"], "raw_text": raw})
    assert r.status_code == 201, r.text
