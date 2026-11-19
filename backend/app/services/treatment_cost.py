"""
Treatment cost estimate: what one treatment is likely to cost at a given hospital, built line by line.

Member 1's model estimates a person's medical expenses for a year from their profile; it never sees
the treatment. This estimate starts from the treatment itself:

1. **Package rate** — the government's all-inclusive price for the treatment under AB PM-JAY
   (Health Benefit Package 2022, Tier-3 city rates, general ward, standard length of stay;
   implants priced separately). Real, published figures.
2. **Hospital type and city** — scaled by the multipliers Member 3's trained fair-price model
   (Random Forest) learnt for procedures, relative to a private hospital in a tier-3 city.
3. **Extra days, ICU, room category** — priced per day from the package's ward and HDU rates and the
   fair-price model's room-rent prediction.
4. **Emergency admission and other illnesses** — percentage uplifts. These are our assumptions and
   are labelled as such everywhere they appear.

The result is a range: ± the fair-price model's average error on unseen data.
"""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

SOURCE_PACKAGE = "AB PM-JAY HBP 2022"
SOURCE_MODEL = "Fair-price model (Member 3)"
SOURCE_ASSUMPTION = "Assumption"

# HBP 2022 medical management, per day (all inclusive)
WARD_PER_DAY = 2310
HDU_PER_DAY = 3300
# ICU without ventilator: not legible in the copy of HBP 2022 we used; taken as twice the ward rate
ICU_PER_DAY = 2 * WARD_PER_DAY

# Assumptions (shown on the page with this label)
EMERGENCY_UPLIFT = 0.15
ROOM_UPGRADE = {  # extra per day, as a share of the fair-price model's room-rent prediction
    "general_ward": 0.0, "semi_private": 0.5, "private": 1.0, "deluxe": 2.0,
}
ROOM_LABEL = {"general_ward": "General ward", "semi_private": "Semi-private room", "private": "Private room",
              "deluxe": "Deluxe / suite"}
CONDITIONS = {  # extra share of the package, extra ward days, extra ICU days
    "diabetes": ("Diabetes", 0.10, 1, 0),
    "hypertension": ("High blood pressure", 0.05, 0, 0),
    "heart_disease": ("Heart disease", 0.15, 0, 1),
    "kidney_disease": ("Kidney disease", 0.15, 1, 0),
}
SENIOR_AGE, SENIOR_EXTRA_DAYS = 60, 1

PERFORMANCE = Path(__file__).resolve().parent.parent / "data" / "model_performance.json"
DEFAULT_RANGE = 0.157


@dataclass(frozen=True)
class Treatment:
    key: str
    name: str
    code: str
    package_name: str  # as printed in HBP 2022
    specialty: str
    los: int  # standard length of stay in the package (days)
    package: int = 0  # all-inclusive package rate, Tier-3 city, general ward
    implant: int = 0
    implant_name: Optional[str] = None
    per_day: bool = False  # medical management: paid per day of stay
    tags: tuple = field(default=())


TREATMENTS = [
    Treatment("appendix", "Appendix removal (laparoscopic)", "SG017B", "Lap- Appendicectomy", "General surgery", 3, 21700),
    Treatment("gallbladder", "Gallbladder removal (open)", "SG039A", "Cholecystectomy without exploration of CBD - Open",
              "General surgery", 6, 31100),
    Treatment("caesarean", "Caesarean delivery", "SO057A", "Caesarean Delivery", "Obstetrics", 5, 22200),
    Treatment("hysterectomy", "Hysterectomy (abdominal)", "SO010A", "Abdominal Hysterectomy", "Gynaecology", 5, 25700),
    Treatment("cataract", "Cataract surgery (phaco)", "SE020A", "Phaco emulsification with foldable hydrophobic acrylic IOL",
              "Ophthalmology", 1, 5500, 6380, "Foldable hydrophobic IOL (lens)"),
    Treatment("knee", "Total knee replacement", "SB039A", "Primary - Total Knee Replacement", "Orthopaedics", 5, 36400,
              60500, "Knee replacement implant"),
    Treatment("fracture", "Fracture fixation, long bone (ORIF)", "SB010A", "ORIF Long Bones", "Orthopaedics", 4, 20800,
              6600, "Plate (diaphyseal, one plate)"),
    Treatment("kidney_stone", "Kidney stone removal (PCNL, one side)", "SU007A", "PCNL (Percutaneous Nephrolithotomy) - U/L",
              "Urology", 2, 45000),
    Treatment("tonsils", "Tonsillectomy (both sides)", "SL016B", "Tonsillectomy - B/L", "ENT", 2, 12200),
    Treatment("dengue", "Dengue fever", "MG004A", "Dengue fever (routine ward)", "General medicine", 4, per_day=True),
    Treatment("typhoid", "Typhoid (enteric fever)", "MG006A", "Enteric fever (routine ward)", "General medicine", 4, per_day=True),
    Treatment("pneumonia", "Pneumonia", "MG016A", "Pneumonia (routine ward)", "General medicine", 4, per_day=True),
]
BY_KEY = {t.key: t for t in TREATMENTS}


@lru_cache(maxsize=1)
def _fair_price():
    from bill_app.ml.ml_bill_scorer import MLBillScorer

    return MLBillScorer()


def _range() -> float:
    try:
        return float(json.loads(PERFORMANCE.read_text())["bill"]["fair_price"]["metrics"]["mape_pct"]) / 100
    except Exception:
        return DEFAULT_RANGE


def multipliers(city_tier: str, hospital_type: str) -> dict:
    """Hospital-type and city effects learnt by Member 3's fair-price model for procedures."""
    fp = _fair_price()
    base = fp.predict_fair_price("procedure", "tier3", "private")
    same_city = fp.predict_fair_price("procedure", "tier3", hospital_type)
    target = fp.predict_fair_price("procedure", city_tier, hospital_type)
    return {"hospital": same_city / base, "city": target / same_city,
            "room_per_day": fp.predict_fair_price("room_rent", city_tier, hospital_type, 1)}


def estimate(key: str, city_tier: str, hospital_type: str, ward_days: Optional[int] = None, icu_days: int = 0,
             room: str = "general_ward", emergency: bool = False, conditions: tuple = (), age: Optional[int] = None) -> dict:
    t = BY_KEY[key]
    m = multipliers(city_tier, hospital_type)
    scale = m["hospital"] * m["city"]
    ward_days = t.los if ward_days is None else max(int(ward_days), 0 if t.per_day else 1)
    icu_days = max(int(icu_days), 0)

    steps = []  # the waterfall: how each factor moves the price

    def add(factor, amount, detail, source, line=None):
        steps.append({"factor": factor, "amount": round(amount), "detail": detail, "source": source, "line": line})

    base = t.package if not t.per_day else WARD_PER_DAY * t.los
    add("Package rate", base,
        f"{t.code} {t.package_name}: {t.los} days, general ward, medicines and tests included, Tier-3 city"
        if not t.per_day else f"{t.code} {t.package_name}: ₹{WARD_PER_DAY:,}/day × {t.los} days, all inclusive",
        SOURCE_PACKAGE, "package")
    add("Hospital type", base * (m["hospital"] - 1), f"{hospital_type.replace('_', ' ')} hospital: × {m['hospital']:.2f}",
        SOURCE_MODEL, "package")
    add("City", base * m["hospital"] * (m["city"] - 1), f"{city_tier} city: × {m['city']:.2f}", SOURCE_MODEL, "package")
    package = base * scale

    extra = ward_days - t.los if t.per_day else max(ward_days - t.los, 0)
    if extra:
        add("Longer stay" if extra > 0 else "Shorter stay", extra * WARD_PER_DAY * scale,
            f"{extra:+d} ward day{'s' if abs(extra) != 1 else ''} × ₹{WARD_PER_DAY * scale:,.0f}", SOURCE_PACKAGE, "stay")
    if icu_days:
        add("ICU", icu_days * ICU_PER_DAY * scale, f"{icu_days} day{'s' if icu_days != 1 else ''} × ₹{ICU_PER_DAY * scale:,.0f} "
            f"(ICU taken as twice the ward rate)", SOURCE_ASSUMPTION, "icu")
    total_ward = max(ward_days, t.los) if not t.per_day else ward_days
    if ROOM_UPGRADE.get(room):
        per = m["room_per_day"] * ROOM_UPGRADE[room]
        add("Room category", total_ward * per, f"{ROOM_LABEL[room]}: +₹{per:,.0f}/day × {total_ward} days "
            f"(the package is priced for a general ward)", SOURCE_MODEL, "room")
    if emergency:
        add("Emergency admission", package * EMERGENCY_UPLIFT, f"+{EMERGENCY_UPLIFT:.0%} of the package", SOURCE_ASSUMPTION, "extra")

    for c in conditions:
        if c not in CONDITIONS:
            continue
        label, pct, days, icu = CONDITIONS[c]
        amount = package * pct + days * WARD_PER_DAY * scale + icu * ICU_PER_DAY * scale
        bits = [f"+{pct:.0%} of the package"] + ([f"+{days} ward day"] if days else []) + ([f"+{icu} ICU day"] if icu else [])
        add(label, amount, ", ".join(bits), SOURCE_ASSUMPTION, "extra")
    if age is not None and age >= SENIOR_AGE:
        add(f"Age {SENIOR_AGE}+", SENIOR_EXTRA_DAYS * WARD_PER_DAY * scale, f"+{SENIOR_EXTRA_DAYS} ward day (slower recovery)",
            SOURCE_ASSUMPTION, "stay")
    if t.implant:
        add("Implant", t.implant, f"{t.implant_name}, at the package's listed implant price", SOURCE_PACKAGE, "implant")

    total = sum(s["amount"] for s in steps)
    spread = _range()
    return {
        "treatment": {"key": t.key, "name": t.name, "code": t.code, "specialty": t.specialty, "standard_days": t.los},
        "inputs": {"city_tier": city_tier, "hospital_type": hospital_type, "ward_days": ward_days, "icu_days": icu_days,
                   "room": room, "emergency": emergency, "conditions": list(conditions), "age": age},
        "steps": steps,
        "total": round(total),
        "low": round(total * (1 - spread)),
        "high": round(total * (1 + spread)),
        "range_pct": round(spread * 100, 1),
        "multipliers": {k: round(v, 3) for k, v in m.items()},
    }


def bill_lines(result: dict) -> list[tuple[str, str, float]]:
    """The estimate as bill lines (description, category, amount) for Member 3's cost calculator."""
    name = result["treatment"]["name"]
    groups = {"package": (f"Treatment package - {name}", "procedure"), "stay": ("Additional ward stay", "room_rent"),
              "icu": ("ICU charges", "procedure"), "room": ("Room upgrade", "room_rent"),
              "extra": ("Emergency / other conditions", "procedure"), "implant": ("Implant", "procedure")}
    totals: dict[str, float] = {}
    for s in result["steps"]:
        totals[s["line"]] = totals.get(s["line"], 0) + s["amount"]
    return [(groups[k][0], groups[k][1], v) for k, v in totals.items() if v > 0]
