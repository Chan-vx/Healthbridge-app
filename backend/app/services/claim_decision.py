"""
Claim Decision Engine: recommends what the insurer should do with a claim.

Why not a trained model: Member 2's claim-approval XGBoost (src/22) reaches 36%
accuracy on 3 balanced classes (guessing = 34%, ROC-AUC 0.54), because ClaimStatus
in the dataset is unrelated to every claim feature. Instead this engine follows how
insurers adjudicate claims, using the signals the platform's models already produce:

  * Member 2 — hybrid fraud risk (XGBoost + Isolation Forest)      -> hold / verify
  * Member 3 — duplicate lines (text similarity)                  -> not payable
  * Member 3 — fair price (Random Forest) + anomaly (Isolation F.) -> pay only up to
               the "reasonable and customary" price: fair price + 25%
  * the policy — deductible, co-insurance, copay, caps, sum insured, re-applied by
               Member 3's cost calculator to the adjusted bill

The result is advice; the insurer still makes the decision.
"""

from typing import Optional

from app.models import Bill, Claim, Policy
from app.services.ml import registry

REASONABLE_MARGIN = 1.25  # pay at most 25% above the predicted fair market price

DECISIONS = {
    "approve": "Approve in full",
    "approve_reduced": "Approve a reduced amount",
    "verify": "Approve after verification",
    "investigate": "Hold for investigation",
    "reject": "Reject: nothing payable",
}


def _policy(policy: Optional[Policy]):
    analyzer = registry.bill
    if policy is None:
        return analyzer.InsurancePolicy()
    return analyzer.InsurancePolicy(
        deductible=policy.deductible, co_insurance_pct=policy.co_insurance_pct, copay_flat=policy.copay_flat,
        category_caps={"room_rent": policy.room_rent_cap} if policy.room_rent_cap else {},
        overall_cap=policy.sum_insured,
    )


def recommend(claim: Claim) -> Optional[dict]:
    bill: Optional[Bill] = claim.bill
    if bill is None or registry.bill is None:
        return None
    analyzer = registry.bill

    deductions, adjusted, review_items = [], [], []
    for item in bill.items:
        allowed = item.amount
        if item.duplicate_of:
            allowed = 0.0
            deductions.append({
                "description": item.description, "billed": item.amount, "deducted": item.amount,
                "reason": f"Duplicate of \"{item.duplicate_of}\" ({item.duplicate_similarity}% similar)",
            })
        elif item.severity == "high_risk" and item.fair_price:
            allowed = min(item.amount, round(item.fair_price * REASONABLE_MARGIN, 2))
            if allowed < item.amount:
                deductions.append({
                    "description": item.description, "billed": item.amount,
                    "deducted": round(item.amount - allowed, 2),
                    "reason": f"{item.overcharge_pct:+.0f}% over the fair price of ₹{item.fair_price:,.0f}; "
                              f"paid up to fair price + 25%",
                })
        elif item.severity == "review":
            review_items.append(item.description)
        adjusted.append(analyzer.BillLineItem(item.description, item.category, allowed, is_covered=item.is_covered))

    cost = analyzer.CostCalculator(_policy(claim.policy)).calculate(adjusted)
    recommended = round(min(cost.insurance_pays, claim.claim_amount), 2)
    total_deducted = round(sum(d["deducted"] for d in deductions), 2)

    checks = [
        {"name": "Policy active", "ok": bool(claim.policy and claim.policy.active),
         "detail": claim.policy.policy_number if claim.policy else "No policy"},
        {"name": "Fraud risk", "ok": claim.risk_level == "LOW",
         "detail": f"{claim.risk_level} (hybrid score {claim.hybrid_risk_score:.3f})"},
        {"name": "No duplicate charges", "ok": not any("Duplicate" in d["reason"] for d in deductions),
         "detail": f"{sum(1 for i in bill.items if i.duplicate_of)} duplicate line(s)"},
        {"name": "Prices within fair range", "ok": not any(i.severity == "high_risk" for i in bill.items),
         "detail": f"{sum(1 for i in bill.items if i.severity == 'high_risk')} overcharged, "
                   f"{len(review_items)} to review"},
        {"name": "Printed total matches items", "ok": not bill.total_mismatch,
         "detail": "Matches" if not bill.total_mismatch else
                   f"Printed ₹{bill.stated_total:,.0f} vs items ₹{bill.total_billed:,.0f}"},
        {"name": "Within sum insured",
         "ok": not (claim.policy and claim.policy.sum_insured and cost.insurance_pays >= claim.policy.sum_insured),
         "detail": f"Sum insured ₹{claim.policy.sum_insured:,.0f}" if claim.policy and claim.policy.sum_insured
                   else "No limit"},
    ]

    if claim.risk_level == "HIGH":
        decision = "investigate"
        summary = "The fraud model rates this claim HIGH risk. Hold payment until an investigator reviews it."
    elif recommended <= 0:
        decision = "reject"
        summary = ("After removing duplicate and overpriced charges, the remaining bill is within the patient's "
                   "deductible or not covered, so insurance owes nothing.")
    elif claim.risk_level == "MEDIUM" or bill.total_mismatch or review_items:
        decision = "verify"
        reasons = []
        if claim.risk_level == "MEDIUM":
            reasons.append("the fraud risk is MEDIUM")
        if bill.total_mismatch:
            reasons.append("the printed total does not match the items")
        if review_items:
            reasons.append(f"{len(review_items)} charge(s) are well above the fair price")
        summary = "Check the documents before paying: " + "; ".join(reasons) + "."
    elif total_deducted > 0:
        decision = "approve_reduced"
        summary = f"Pay the claim without the duplicate or overpriced charges (₹{total_deducted:,.0f} of the bill removed)."
    else:
        decision = "approve"
        summary = "All checks passed. Pay the claimed amount."

    return {
        "decision": decision,
        "label": DECISIONS[decision],
        "summary": summary,
        "claimed_amount": claim.claim_amount,
        "recommended_amount": recommended,
        "saving": round(max(claim.claim_amount - recommended, 0), 2),
        "bill_deductions": deductions,
        "total_deducted_from_bill": total_deducted,
        "review_items": review_items,
        "checks": checks,
        "method": "Policy rules + Member 2 fraud risk + Member 3 fair prices and duplicate detection",
    }
