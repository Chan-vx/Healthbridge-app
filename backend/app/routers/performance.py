"""How well each model does on data it was not trained on (written by evaluation/evaluate_models.py)."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.models import User
from app.security import get_current_user

router = APIRouter(prefix="/api/models", tags=["model performance"])

RESULTS = Path(__file__).resolve().parent.parent / "data" / "model_performance.json"


@router.get("/performance", summary="Test-set results for every model")
def performance(_: User = Depends(get_current_user)):
    if not RESULTS.exists():
        raise HTTPException(404, "No evaluation results yet. Run: python evaluation/evaluate_models.py")
    return json.loads(RESULTS.read_text())
