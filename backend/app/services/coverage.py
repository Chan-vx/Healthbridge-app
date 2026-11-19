"""
How much of a policy's sum insured is left in the current policy year.

The sum insured is a yearly limit, as in real Indian health policies: every claim in the policy year
uses part of it. A policy year runs from the policy's start date to the day before its next anniversary.

    used     approved and settled claims (the approved amount)
    pending  claims submitted and not yet decided (the claimed amount, held until the insurer decides)
    left     sum insured - used - pending

New bills are split with the amount left as the insurer's limit, and a claim can never ask for, or be
approved for, more than is left.
"""

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Claim, Policy

USED = ("approved", "settled")
PENDING = ("submitted",)


def _anniversary(start: date, year: int) -> date:
    try:
        return start.replace(year=year)
    except ValueError:  # 29 February
        return start.replace(year=year, day=28)


def policy_year(policy: Policy, on: Optional[date] = None) -> tuple[date, date]:
    """First and last day of the policy year containing `on` (today by default)."""
    on = on or datetime.now(timezone.utc).date()
    start = policy.created_at.date()
    begin = _anniversary(start, on.year)
    if begin > on:
        begin = _anniversary(start, on.year - 1)
    end = _anniversary(begin, begin.year + 1)
    return begin, date.fromordinal(end.toordinal() - 1)


def claim_value(claim: Claim) -> float:
    return float(claim.approved_amount or 0) if claim.status in USED else float(claim.claim_amount or 0)


def usage(db: Session, policy: Policy, exclude_claim_id: Optional[int] = None, on: Optional[date] = None) -> dict:
    begin, end = policy_year(policy, on)
    claims = [c for c in db.scalars(select(Claim).where(Claim.policy_id == policy.id).order_by(Claim.submitted_at))
              if begin <= c.submitted_at.date() <= end]
    counted = [c for c in claims if c.id != exclude_claim_id]
    used = sum(claim_value(c) for c in counted if c.status in USED)
    pending = sum(claim_value(c) for c in counted if c.status in PENDING)
    return {
        "year_start": begin.isoformat(), "year_end": end.isoformat(),
        "sum_insured": round(policy.sum_insured, 2), "used": round(used, 2), "pending": round(pending, 2),
        "left": round(max(policy.sum_insured - used - pending, 0.0), 2),
        "claims": [{"id": c.id, "claim_number": c.claim_number, "status": c.status, "submitted_at": c.submitted_at.isoformat(),
                    "claim_amount": c.claim_amount, "approved_amount": c.approved_amount, "counts": c.status in USED + PENDING}
                   for c in claims],
    }


def left(db: Session, policy: Policy, exclude_claim_id: Optional[int] = None) -> float:
    return usage(db, policy, exclude_claim_id)["left"]
