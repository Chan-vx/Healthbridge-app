"""Each patient, hospital and insurer account can clear its own records (app/services/account_records.py)."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import require_roles
from app.services import account_records

router = APIRouter(prefix="/api/account", tags=["account"])


class ClearRequest(BaseModel):
    action: Literal["reset", "delete"]


@router.get("/records", summary="How many records this account has")
def my_records(user: User = Depends(require_roles(*account_records.ROLES)), db: Session = Depends(get_db)):
    return {"role": user.role, "counts": account_records.counts(db, user)}


@router.post("/records/clear", summary="Delete this account's records, or reset them to the demo data")
def clear_my_records(body: ClearRequest, user: User = Depends(require_roles(*account_records.ROLES)),
                     db: Session = Depends(get_db)):
    return account_records.clear(db, user, body.action)
