import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.routers import auth, bills, claims, dashboard, patients, policies
from app.services.ml import FraudModel, registry

log = logging.getLogger("healthbridge")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    registry.load()  # every model is loaded once here, not per request
    for name, error in registry.errors.items():
        log.error("Model %s failed to load: %s", name, error)
    if settings.seed_demo:
        from app.seed import seed

        with SessionLocal() as db:
            seed(db)
    yield


app = FastAPI(
    title="HealthBridge API",
    description="Digital healthcare finance and insurance platform. Integrates the cost prediction (Member 1), "
                "fraud & insurance (Member 2) and bill & finance (Member 3) modules behind one authenticated API.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth, patients, policies, bills, claims, dashboard):
    app.include_router(r.router)


@app.get("/api/health", tags=["system"])
def health():
    database = "ok"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        database = f"error: {exc}"
    models = registry.status()
    ok = database == "ok" and all(m["loaded"] for m in models.values())
    return {"status": "healthy" if ok else "degraded", "database": database, "models": models}


@app.get("/api/meta/options", tags=["system"])
def options():
    """Allowed values for the frontend's dropdowns."""
    return {
        "regions": ["northeast", "northwest", "southeast", "southwest"],
        "specialties": FraudModel.SPECIALTIES,
        "claim_types": FraudModel.CLAIM_TYPES,
        "submission_methods": FraudModel.SUBMISSION_METHODS,
        "marital_statuses": FraudModel.MARITAL,
        "employment_statuses": FraudModel.EMPLOYMENT,
        "city_tiers": ["metro", "tier2", "tier3"],
        "hospital_types": ["government", "private", "multispeciality", "premium"],
        "categories": ["room_rent", "procedure", "medicine", "diagnostic", "nursing", "consultation", "cosmetic",
                       "other"],
        "usd_to_inr": settings.usd_to_inr,
    }
