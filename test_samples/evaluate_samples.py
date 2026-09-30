"""
Runs every test bill through the real pipeline (OCR -> Member 3 -> Member 2) without
touching the database, and prints the results the website should show.

Inside the backend container:
    docker compose cp test_samples backend:/srv/test_samples
    docker compose exec backend python test_samples/evaluate_samples.py
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, "/srv")
from app.services.ml import registry  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# demo policies and profiles from app/seed.py
POLICIES = {
    "Arjun": dict(deductible=0, co_insurance_pct=10, copay_flat=1000, room_rent_cap=15000, sum_insured=1000000),
    "Priya": dict(deductible=10000, co_insurance_pct=10, copay_flat=0, room_rent_cap=None, sum_insured=500000),
    "Ramesh": dict(deductible=5000, co_insurance_pct=20, copay_flat=500, room_rent_cap=20000, sum_insured=150000),
    "Meena": None,
}
PROFILES = {
    "Arjun": dict(age=58, sex="male", monthly_income=18000, existing_monthly_debt=0, marital="Married", employment="Retired"),
    "Priya": dict(age=32, sex="female", monthly_income=85000, existing_monthly_debt=12000, marital="Married", employment="Employed"),
    "Ramesh": dict(age=45, sex="male", monthly_income=22000, existing_monthly_debt=3000, marital="Married", employment="Employed"),
    "Meena": dict(age=27, sex="female", monthly_income=0, existing_monthly_debt=0, marital="Single", employment="Student"),
}
HOSPITALS = {"citycare": ("metro", "multispeciality", "Chennai"), "sunrise": ("tier2", "private", "Coimbatore")}
CASES = [
    ("bill_01_clean_sunrise.png", "Arjun", "sunrise", "Inpatient", "General Practice"),
    ("bill_02_overcharged_citycare.png", "Priya", "citycare", "Inpatient", "General Practice"),
    ("bill_03_duplicates_sunrise.png", "Ramesh", "sunrise", "Inpatient", "General Practice"),
    ("bill_04_total_mismatch_citycare.png", "Meena", "citycare", None, None),
    ("bill_05_inflated_cardiac_citycare.png", "Arjun", "citycare", "Inpatient", "Cardiology"),
    ("bill_06_clean_sunrise.pdf", "Arjun", "sunrise", "Inpatient", "General Practice"),
    ("new_bills/new_bill_01_maternity_citycare.png", "Priya", "citycare", "Inpatient", "General Practice"),
    ("new_bills/new_bill_02_dengue_sunrise.png", "Ramesh", "sunrise", "Inpatient", "General Practice"),
    ("new_bills/new_bill_03_fracture_sunrise.png", "Arjun", "sunrise", "Inpatient", "Orthopedics"),
    ("new_bills/new_bill_04_ent_no_insurance_citycare.png", "Meena", "citycare", None, None),
    ("new_bills/new_bill_05_appendix_citycare.png", "Priya", "citycare", "Emergency", "General Practice"),
    ("new_bills/new_bill_06_spine_inflated_citycare.png", "Arjun", "citycare", "Inpatient", "Orthopedics"),
    ("new_bills/new_bill_07_appendix_citycare.pdf", "Priya", "citycare", "Emergency", "General Practice"),
]

registry.load()
bill = registry.bill
for filename, patient, hosp, claim_type, specialty in CASES:
    tier, htype, city = HOSPITALS[hosp]
    prof = PROFILES[patient]
    parsed = bill.parse(bill.ocr(os.path.join(HERE, filename)))
    result = bill.analyze(parsed["line_items"], tier, htype, POLICIES[patient],
                          {"monthly_income": prof["monthly_income"], "existing_monthly_debt": prof["existing_monthly_debt"]})
    c, det = result["cost_breakdown"], result["detection"]
    print(f"\n=== {filename}  (patient {patient}, hospital {hosp})")
    print(f"items read: {len(parsed['line_items'])}  stated {parsed['stated_total']}  computed {parsed['computed_total']}  mismatch {parsed['total_mismatch']}")
    for s in det["ml_price_analysis"]:
        print(f"   {s['description'][:34]:<34} {s['billed_amount']:>10,.0f}  fair {s['fair_price_predicted']:>10,.0f}  {s['overcharge_pct']:+7.1f}%  {s['severity']}")
    for d in det["duplicate_charges"]:
        print(f"   DUPLICATE: '{d['description']}' ~ '{d['matched_with']}' {d['similarity_pct']}%")
    print(f"summary {det['summary']}")
    print(f"insurance {c['insurance_pays']:,.2f}  patient {c['patient_out_of_pocket']:,.2f}")
    if result["recommendations"]:
        print("top option:", result["recommendations"][0]["option"], result["recommendations"][0]["suitability_score"])
    if result["emi"]:
        print("EMI 12m @13.5%:", result["emi"]["plan"]["monthly_emi"])
    if claim_type and c["insurance_pays"] > 0:
        f = registry.fraud.score(c["insurance_pays"], prof["age"], prof["sex"], prof["monthly_income"] * 12,
                                 prof["marital"], prof["employment"], specialty, city, claim_type, "Online",
                                 datetime(2026, 9, 28))
        print(f"CLAIM: fraud_prob {f['fraud_probability']}  anomaly {f['anomaly_score']}  hybrid {f['hybrid_risk_score']}  {f['risk_level']}")

cost = registry.cost
print("\n=== cost model profiles")
for p in [
    (19, "female", 22.0, 0, "no", "northwest"), (30, "male", 26.5, 1, "no", "southeast"),
    (45, "male", 31.2, 2, "no", "southeast"), (45, "male", 31.2, 2, "yes", "southeast"),
    (60, "female", 35.0, 3, "yes", "southwest"), (52, "female", 24.0, 0, "no", "northeast"),
]:
    r = cost.predict(*p)
    top = r["shap"][0]
    print(p, "->", r["predicted_usd"], "| top factor", top["feature"], round(top["shap_usd"]))
