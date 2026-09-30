"""Aggregated numbers for each role's dashboard (including Member 3's financial dashboard data)."""

from collections import Counter, defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Bill, Claim, CostEstimate, Hospital, Payment, Policy, User
from app.routers.bills import summary_out
from app.routers.claims import claim_out
from app.routers.policies import active_policy, policy_out
from app.security import require_roles
from app.services.ml import registry

router = APIRouter(prefix="/api/dashboard", tags=["dashboards"])


def _money(x: float) -> float:
    return round(float(x or 0), 2)


def _month(dt) -> str:
    return dt.strftime("%Y-%m")


def _claims_summary(claims: list[Claim]) -> dict:
    status = Counter(c.status for c in claims)
    risk = Counter(c.risk_level for c in claims)
    decided = status["approved"] + status["settled"] + status["rejected"]
    return {
        "count": len(claims),
        "by_status": {s: status.get(s, 0) for s in ("submitted", "approved", "rejected", "settled")},
        "by_risk": {r: risk.get(r, 0) for r in ("HIGH", "MEDIUM", "LOW")},
        "claimed_amount": _money(sum(c.claim_amount for c in claims)),
        "approved_amount": _money(sum(c.approved_amount or 0 for c in claims if c.status in ("approved", "settled"))),
        "settled_amount": _money(sum(c.approved_amount or 0 for c in claims if c.status == "settled")),
        "approval_rate": round((status["approved"] + status["settled"]) / decided, 3) if decided else None,
        "fraud_flagged": sum(1 for c in claims if c.fraud_prediction == 1),
        "avg_hybrid_risk": round(sum(c.hybrid_risk_score for c in claims) / len(claims), 4) if claims else None,
    }


def _bill_totals(bills: list[Bill]) -> dict:
    return {
        "count": len(bills),
        "total_billed": _money(sum(b.total_billed for b in bills)),
        "insurance_share": _money(sum(b.insurance_pays for b in bills)),
        "patient_share": _money(sum(b.patient_out_of_pocket for b in bills)),
        "flagged_amount": _money(sum(b.flagged_amount for b in bills)),
        "duplicates": sum(b.duplicate_count for b in bills),
        "high_risk_items": sum(b.high_risk_count for b in bills),
        "unpaid_patient_dues": _money(sum(b.patient_out_of_pocket for b in bills if b.payment_status == "unpaid")),
    }


def _monthly_bills(bills: list[Bill]) -> list[dict]:
    rows = defaultdict(lambda: {"billed": 0.0, "insurance": 0.0, "patient": 0.0, "flagged": 0.0, "bills": 0})
    for b in bills:
        r = rows[_month(b.created_at)]
        r["billed"] += b.total_billed
        r["insurance"] += b.insurance_pays
        r["patient"] += b.patient_out_of_pocket
        r["flagged"] += b.flagged_amount
        r["bills"] += 1
    return [{"month": m, **{k: _money(v) if k != "bills" else v for k, v in r.items()}} for m, r in sorted(rows.items())]


def _monthly_claims(claims: list[Claim]) -> list[dict]:
    rows = defaultdict(lambda: {"claims": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "claimed": 0.0})
    for c in claims:
        r = rows[_month(c.submitted_at)]
        r["claims"] += 1
        r[c.risk_level] += 1
        r["claimed"] += c.claim_amount
    return [{"month": m, **r, "claimed": _money(r["claimed"])} for m, r in sorted(rows.items())]


@router.get("/patient")
def patient_dashboard(user: User = Depends(require_roles("patient")), db: Session = Depends(get_db)):
    bills = db.scalars(select(Bill).where(Bill.patient_id == user.id).order_by(Bill.created_at.desc())).all()
    claims = db.scalars(select(Claim).where(Claim.patient_id == user.id).order_by(Claim.submitted_at.desc())).all()
    estimate = db.scalar(select(CostEstimate).where(CostEstimate.patient_id == user.id)
                         .order_by(CostEstimate.created_at.desc()))
    payments = db.scalars(select(Payment).where(Payment.patient_id == user.id)).all()
    policy = active_policy(db, user.id)
    return {
        "bills": _bill_totals(bills),
        "claims": _claims_summary(claims),
        "active_policy": policy_out(policy).model_dump() if policy else None,
        "latest_estimate": {"predicted_usd": estimate.predicted_usd, "predicted_inr": estimate.predicted_inr,
                            "shap": estimate.shap, "inputs": estimate.inputs,
                            "created_at": estimate.created_at.isoformat()} if estimate else None,
        "emi_monthly_total": _money(sum(p.monthly_emi for p in payments if p.plan == "emi")),
        "recent_bills": [summary_out(db, b).model_dump() for b in bills[:5]],
        "recent_claims": [claim_out(c).model_dump() for c in claims[:5]],
    }


@router.get("/hospital")
def hospital_dashboard(user: User = Depends(require_roles("hospital")), db: Session = Depends(get_db)):
    hid = user.hospital.id
    bills = db.scalars(select(Bill).where(Bill.hospital_id == hid).order_by(Bill.created_at.desc())).all()
    claims = db.scalars(select(Claim).where(Claim.hospital_id == hid).order_by(Claim.submitted_at.desc())).all()
    summary = _claims_summary(claims)
    return {
        "hospital": {"name": user.hospital.name, "city": user.hospital.city,
                     "city_tier": user.hospital.city_tier, "hospital_type": user.hospital.hospital_type},
        "bills": _bill_totals(bills),
        "claims": summary,
        "revenue": {
            "billed": _money(sum(b.total_billed for b in bills)),
            "insurance_receivable": _money(summary["approved_amount"] - summary["settled_amount"]),
            "insurance_settled": summary["settled_amount"],
            "insurance_pending": _money(sum(c.claim_amount for c in claims if c.status == "submitted")),
            "patient_collected": _money(sum(b.patient_out_of_pocket for b in bills if b.payment_status != "unpaid")),
            "patient_outstanding": _money(sum(b.patient_out_of_pocket for b in bills if b.payment_status == "unpaid")),
        },
        "monthly": _monthly_bills(bills),
        "unclaimed_bills": [summary_out(db, b).model_dump() for b in bills
                            if b.policy_id and b.insurance_pays > 0
                            and not any(c.bill_id == b.id and c.status != "rejected" for c in claims)][:10],
        "recent_bills": [summary_out(db, b).model_dump() for b in bills[:8]],
        "recent_claims": [claim_out(c).model_dump() for c in claims[:8]],
    }


@router.get("/insurer")
def insurer_dashboard(user: User = Depends(require_roles("insurer")), db: Session = Depends(get_db)):
    iid = user.insurer.id
    claims = db.scalars(select(Claim).where(Claim.insurer_id == iid).order_by(Claim.submitted_at.desc())).all()
    policies = db.scalars(select(Policy).where(Policy.insurer_id == iid, Policy.active.is_(True))).all()

    providers = defaultdict(lambda: {"claims": 0, "high": 0, "risk_sum": 0.0, "claimed": 0.0})
    for c in claims:
        p = providers[c.hospital.name if c.hospital else "Direct (patient)"]
        p["claims"] += 1
        p["high"] += c.risk_level == "HIGH"
        p["risk_sum"] += c.hybrid_risk_score
        p["claimed"] += c.claim_amount
    provider_risk = sorted(
        ({"provider": name, "claims": v["claims"], "high_risk": v["high"],
          "avg_hybrid_risk": round(v["risk_sum"] / v["claims"], 4), "claimed": _money(v["claimed"])}
         for name, v in providers.items()),
        key=lambda r: -r["avg_hybrid_risk"],
    )
    factors = Counter()
    for c in claims:
        for f in c.top_factors[:3]:
            if f.get("impact", 0) > 0:
                factors[f["feature"]] += 1
    queue = [c for c in claims if c.status == "submitted"]
    queue.sort(key=lambda c: -c.hybrid_risk_score)
    return {
        "insurer": {"name": user.insurer.name},
        "active_policies": len(policies),
        "claims": _claims_summary(claims),
        "monthly": _monthly_claims(claims),
        "provider_risk": provider_risk,
        "top_risk_factors": [{"feature": f, "claims": n} for f, n in factors.most_common(6)],
        "queue": [claim_out(c).model_dump() for c in queue[:10]],
    }


@router.get("/finance")
def finance_dashboard(_: User = Depends(require_roles("finance", "admin")), db: Session = Depends(get_db)):
    bills = db.scalars(select(Bill)).all()
    claims = db.scalars(select(Claim)).all()
    payments = db.scalars(select(Payment)).all()
    hospitals = {h.id: h.name for h in db.scalars(select(Hospital))}

    per_hospital = defaultdict(lambda: {"bills": 0, "billed": 0.0, "insurance": 0.0, "patient": 0.0,
                                        "flagged": 0.0, "claims": 0, "risk_sum": 0.0})
    for b in bills:
        h = per_hospital[hospitals.get(b.hospital_id, b.hospital_name or "Unlinked")]
        h["bills"] += 1
        h["billed"] += b.total_billed
        h["insurance"] += b.insurance_pays
        h["patient"] += b.patient_out_of_pocket
        h["flagged"] += b.flagged_amount
    for c in claims:
        h = per_hospital[hospitals.get(c.hospital_id, "Unlinked")]
        h["claims"] += 1
        h["risk_sum"] += c.hybrid_risk_score

    emi_plans = [p for p in payments if p.plan == "emi"]
    recs = Counter(b.recommendations[0]["option"] for b in bills if b.recommendations)
    return {
        "bills": _bill_totals(bills),
        "claims": _claims_summary(claims),
        "payments": {
            "paid_in_full": _money(sum(p.principal for p in payments if p.plan == "full")),
            "on_emi_principal": _money(sum(p.principal for p in emi_plans)),
            "emi_plans": len(emi_plans),
            "emi_interest": _money(sum(p.total_payment - p.principal for p in emi_plans)),
            "emi_monthly_inflow": _money(sum(p.monthly_emi for p in emi_plans)),
        },
        "monthly": _monthly_bills(bills),
        "claims_monthly": _monthly_claims(claims),
        "per_hospital": sorted(
            ({"hospital": name, "bills": v["bills"], "billed": _money(v["billed"]),
              "insurance": _money(v["insurance"]), "patient": _money(v["patient"]),
              "flagged": _money(v["flagged"]), "claims": v["claims"],
              "avg_hybrid_risk": round(v["risk_sum"] / v["claims"], 4) if v["claims"] else None}
             for name, v in per_hospital.items()),
            key=lambda r: -r["billed"],
        ),
        "top_recommendations": [{"option": o, "bills": n} for o, n in recs.most_common()],
    }


@router.get("/admin")
def admin_dashboard(_: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.created_at.desc())).all()
    return {
        "users_by_role": dict(Counter(u.role for u in users)),
        "records": {
            "bills": len(db.scalars(select(Bill.id)).all()),
            "claims": len(db.scalars(select(Claim.id)).all()),
            "policies": len(db.scalars(select(Policy.id)).all()),
            "cost_estimates": len(db.scalars(select(CostEstimate.id)).all()),
            "payments": len(db.scalars(select(Payment.id)).all()),
        },
        "models": registry.status(),
        "users": [{"id": u.id, "full_name": u.full_name, "email": u.email, "role": u.role,
                   "created_at": u.created_at.isoformat()} for u in users],
    }
