# HealthBridge — Application & Integration (Member 4)

One web application that connects the three team modules:

| Module | Owner | Where it lives here | What the app uses it for |
|---|---|---|---|
| Cost prediction (Gradient Boosting + SHAP) | Member 1 | `backend/ml_modules/cost/` | Patient cost estimate with SHAP explanation |
| Fraud & insurance (XGBoost + Isolation Forest + hybrid risk + SHAP) | Member 2 | `backend/ml_modules/fraud/` | Scoring every insurance claim on submission |
| Bill & finance (OCR, fair-price RF, anomaly IF, cost split, EMI, recommendations) | Member 3 | `backend/ml_modules/bill/bill_app/` | Analysing uploaded bills and payment options |

The members' own inference code is imported unchanged (`cost/api/shap_explanation.py`,
`fraud/src/api.py`, `bill/bill_app/*`); `backend/app/services/ml.py` only adapts
platform records to model inputs.

## Run it online (GitHub Codespaces)

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/Chan-vx/Healthbridge-app?quickstart=1)

1. Click the button above (or **Code → Codespaces → Create codespace on main**).
2. Wait about 5–8 minutes the first time while Docker builds everything; the website opens by itself on port 3000.
3. To share it: open the **Ports** tab, right-click port **3000 → Port visibility → Public**, and send the link.

A codespace stops after 30 minutes without use; open it again from **Code → Codespaces** and the app restarts with its data.

## Run it on your own computer

```bash
docker compose up --build
```

- App: http://localhost:3000
- API docs (Swagger): http://localhost:3000/docs
- Health / model status: http://localhost:3000/api/health

The website forwards `/api` and `/docs` to the FastAPI backend, so the whole app needs only one address
(the backend is also reachable directly on port 8000).

On first start the backend seeds demo data (`SEED_DEMO=true`). All demo accounts use
the password **`Demo@1234`** — the login page has one-click buttons:

| Role | Email |
|---|---|
| Patient | ramesh@patient.in, priya@patient.in, arjun@patient.in, meena@patient.in |
| Hospital | citycare@hospital.in (metro, multispeciality), sunrise@hospital.in (tier 2, private) |
| Insurer | claims@suraksha.in |
| Finance | finance@healthbridge.in |
| Admin | admin@healthbridge.in |

To start from an empty database: `docker compose down -v` then `SEED_DEMO=false docker compose up`.

### Without Docker (development)

```bash
# backend (needs a PostgreSQL, or use SQLite)
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
set DATABASE_URL=sqlite:///./healthbridge.db   # or a postgresql+psycopg:// URL
set SEED_DEMO=true
.venv/Scripts/uvicorn app.main:app --reload

# frontend
cd frontend
npm install
npm run dev
```

Image/PDF upload needs Tesseract installed; without it, the "sample bill" and
"enter items" options still work.

### Tests

```bash
cd backend
.venv/Scripts/python -m pytest -q
```

## Architecture

```
Next.js (5 role workspaces) ──JWT──▶ FastAPI ──▶ PostgreSQL (10 tables)
                                       │
                                       ├─▶ Member 1 cost model + SHAP
                                       ├─▶ Member 2 fraud engine (hybrid risk + SHAP)
                                       └─▶ Member 3 bill analyzer (OCR → parse → detect → cost → EMI → advice)
```

Workflow: hospital or patient uploads a bill → Member 3 checks every line and splits
insurance vs patient → the insurance share becomes a claim → Member 2 scores it →
insurer approves/rejects/settles → patient pays the balance in full or on EMI.

## Integration notes (what had to change)

- **One scikit-learn version (1.9.0).** Models were saved with 1.9.0 (M1), 1.6.1 (M2) and
  1.8.0 (M3). Member 2's `robust_preprocessor.pkl` cannot be unpickled by 1.9.x, so it is
  re-fitted by `ml_modules/fraud/rebuild_preprocessor.py` (Member 2's script 11 logic, same
  data and split). Verified identical: transforming the test split gives a maximum
  difference of 0.0 from Member 2's saved `X_test.pkl`, and the confusion matrix is
  still 844 / 2 / 0 / 54.
- **Currency.** M1 and M2 were trained on dollar-scale data; the adapters convert INR at
  `USD_TO_INR` (default 83).
- **Copay fix** in `bill_app/calculators/cost_calculator.py`: the copay is now also
  subtracted from what insurance pays, so insurance + patient = bill.
- **Length of stay** for room rent / nursing is read from the line text or the admission
  and discharge dates instead of a fixed 5 days.
- The Member 3 package was renamed from `app` to `bill_app` to avoid clashing with the
  backend's own `app` package (its files import each other by path, so nothing else changed).

## Not built (future scope)

- A trained claim-approval model. Member 2's `claim_model.pkl` (src/22) reaches 36% accuracy on
  three balanced classes — the same as guessing (34%, ROC-AUC 0.54) — because `ClaimStatus` in the
  dataset is unrelated to every claim feature, so it is not used. Instead the app has a
  **Claim Decision Engine** (`backend/app/services/claim_decision.py`): it combines Member 2's fraud
  risk, Member 3's fair prices and duplicate detection, and the policy terms to recommend
  approve / approve a reduced amount / verify / hold for investigation / reject, with the payable
  amount and itemised reasons. The insurer still decides.
- Revenue / cash-flow forecasting, hospital comparison for patients, expense tracking.
- Cloud deployment (runs locally with Docker Compose).
