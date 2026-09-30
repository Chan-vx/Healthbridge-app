# HealthBridge — test samples and expected results

Every expected value below was produced by running these exact samples through the
real models (OCR → Member 3 → Member 2, and Member 1 for costs) with the demo data.
Open the site at **http://localhost:3000**; every demo password is **`Demo@1234`**.

> The numbers assume the demo profiles and policies are unchanged. If you edit a
> patient's profile or issue them a new policy, their insurance split, payment
> advice and fraud score change accordingly — that is expected.

---

## 1. Bill images (Member 3 OCR pipeline + Member 2 fraud engine)

**How to run each one:**
1. Log in as the **hospital in the file name** (City Care = `citycare@hospital.in`, Sunrise = `sunrise@hospital.in`).
   The hospital decides the fair-price context (City Care = metro + multispeciality, Sunrise = tier 2 + private).
2. Go to **Bills** → tab **Upload image / PDF** → choose the **patient** listed below → choose the file → **Analyse bill**.
3. On the bill page, check the results against the table. Then use **File insurance claim** (claim type and specialty as listed)
   and check the claim's risk.

| File | Log in as | Patient | What it tests |
|---|---|---|---|
| `bill_01_clean_sunrise.png` | Sunrise | Arjun Reddy | A normal bill — nothing should be flagged |
| `bill_02_overcharged_citycare.png` | City Care | Priya Sharma | Overpriced room rent and MRI |
| `bill_03_duplicates_sunrise.png` | Sunrise | Ramesh Kumar | Two duplicate lines |
| `bill_04_total_mismatch_citycare.png` | City Care | Meena Iyer | Printed total ≠ sum of items; patient has no insurance |
| `bill_05_inflated_cardiac_citycare.png` | City Care | Arjun Reddy | Hugely inflated bill → HIGH fraud risk |
| `bill_06_clean_sunrise.pdf` | Sunrise | Arjun Reddy | Same as bill 01, but as a PDF |

### Expected results

**bill_01 — clean (and bill_06, the PDF version: identical)**
- 6 line items read, total **₹13,470**, all six marked **Fair** (within about ±8% of the fair price)
- Flagged: **₹0** · 0 duplicates · 0 overcharges
- Insurance pays **₹11,123** · patient pays **₹2,347** (10% co-insurance ₹1,347 + ₹1,000 copay)
- Top payment option: **Pay in Full (85)** — small amount relative to income
- Claim (Inpatient, General Practice): fraud probability **0.28%**, hybrid **0.112** → **LOW**, "Normal Processing"

**bill_02 — overcharged**
- Total **₹1,31,360**
- **Room Rent (3 days)** ₹45,000 vs fair ₹15,898 → **+183%, Overcharge**
- **MRI Scan Abdomen** ₹18,000 vs fair ₹3,123 → **+476%, Overcharge**
- Everything else Fair · flagged amount **₹63,000**
- Insurance **₹1,09,224** · patient **₹22,136** (₹10,000 deductible + 10% co-insurance)
- Claim: hybrid **0.120** → **LOW** (the fraud model looks at the claim profile, not individual prices — a good point to explain in the viva: Member 3 catches line-level overcharging, Member 2 catches claim-level fraud)

**bill_03 — duplicates**
- 7 items, total **₹9,220**, prices all Fair
- **Duplicate:** "Injection Ceftriaxone" = "Injection Ceftriaxone" (**100%** similar)
- **Duplicate:** "Blood Test CBC" ≈ "Blood Test - CBC" (**93.3%** similar)
- Flagged **₹2,160** (the two repeated lines)
- Insurance **₹2,876** · patient **₹6,344** (₹5,000 deductible + 20% co-insurance + ₹500 copay)
- Claim: hybrid **0.128** → **LOW**

**bill_04 — total mismatch, no insurance**
- Red warning at the top: printed total **₹6,550** does not match the items **₹4,550**
- All 3 items Fair
- Insurance **₹0** · patient **₹4,550** (Meena has no policy)
- **File insurance claim** is not offered (no policy) — correct behaviour
- Top option: **Hospital No-Cost EMI (80)**

**bill_05 — inflated cardiac bill**
- Total **₹8,79,400**
- 5 of 6 lines **Overcharge**: room rent +163%, valve replacement +942%, ICU nursing +341%, echo scan +797%, warfarin +2311%
- Flagged **₹8,09,400**
- Insurance **₹7,22,960** · patient **₹1,56,440**
- Claim (Inpatient, **Cardiology**): fraud probability **99.94%**, anomaly 0.614, hybrid **0.922** → **HIGH**, "Manual Investigation"
- Then log in as **Suraksha** (`claims@suraksha.in`): the claim is at the **top of the queue**; open it to see PatientIncome and ClaimAmount as the main SHAP reasons, and approve or reject it.

**Quick demo without a file:** Bills → **Use sample bill** runs Member 3's original bill (₹1,26,320: duplicate paracetamol 91.3%, CT scan +604.5%, insurance ₹91,356 / patient ₹34,964 for Ramesh).

---

## 2. Bills typed in by hand (tab "Enter items")

Log in as **Sunrise** (`sunrise@hospital.in`), choose **Arjun Reddy**, and type these lines:

**A. Fair outpatient visit**

| Description | Amount |
|---|---|
| Consultation - Physician | 600 |
| X-Ray Chest | 2000 |
| Tablet Paracetamol 500mg | 150 |

Expect: all Fair, nothing flagged. Insurance ₹1,475 · patient ₹1,275.

**B. Catch a duplicate and an overcharge**

| Description | Amount |
|---|---|
| Consultation - Orthopedic | 650 |
| MRI Scan Knee | 12000 |
| Injection Diclofenac | 160 |
| Injection Diclofenac | 160 |

Expect: MRI flagged as **Overcharge** (fair price ₹1,994), the second Diclofenac line flagged **Duplicate (100%)**. Insurance ₹10,673 · patient ₹2,297.

**C. Non-covered item**

| Description | Amount |
|---|---|
| Room Rent (2 days) | 6000 |
| Cosmetic scar gel (non-medical) | 2500 |

Expect: the cosmetic line shows **Covered: No** and its ₹2,500 goes entirely to the patient. Insurance ₹4,400 · patient ₹4,100.

Tip: write days as "(N days)" for room rent and nursing — the fair price is per day.

---

## 3. Cost estimate (Member 1 model)

Log in as a patient (e.g. **Ramesh**) → **Cost estimate** → enter the profile → **Save and estimate**.

| Age | Sex | BMI | Children | Smoker | Region | Expected estimate | Biggest SHAP factor |
|---|---|---|---|---|---|---|---|
| 19 | female | 22.0 | 0 | no | northwest | **$3,107** | Age (lowers, −$4,134) |
| 30 | male | 26.5 | 1 | no | southeast | **$4,866** | Smoker = no (lowers, −$3,658) |
| 45 | male | 31.2 | 2 | no | southeast | **$9,155** | Smoker = no (lowers, −$5,509) |
| 45 | male | 31.2 | 2 | **yes** | southeast | **$41,937** | Smoker = yes (**raises, +$22,010**) |
| 60 | female | 35.0 | 3 | yes | southwest | **$46,639** | Smoker = yes (raises, +$20,626) |
| 52 | female | 24.0 | 0 | no | northeast | **$13,628** | Age (raises, +$4,275) |

The best demo: rows 3 and 4 are the same person except smoking — the estimate jumps from
$9,155 to $41,937 and the smoker bar flips from blue to orange. Also check the line under the
chart: base value + contributions = prediction (SHAP additivity).

> Remember to set Ramesh back to his original profile afterwards (45, male, 31.2, 2, no, southeast,
> Married, Employed, ₹22,000 income, ₹3,000 EMIs) so later bill results match this guide.

---

## 4. Payment and EMI (Member 3 calculators)

Log in as **Priya** (`priya@patient.in`) → **My bills** → open an **Unpaid** bill → **EMI calculator**.

- ₹22,136 at 13.5% for 12 months → **₹1,982.32 / month** (bill_02, if you uploaded it)
- Change months to 6 or 24 and press **Recalculate** — longer tenure, lower EMI, more interest
- **Choose this EMI plan** → the bill becomes **On EMI**; the finance dashboard's "Financed on EMI" goes up

Formula check: EMI = P·r·(1+r)ⁿ / ((1+r)ⁿ − 1), r = 13.5 / 12 / 100 = 0.01125.

---

## 5. Insurance workflow

1. **Issue a policy:** log in as **Suraksha** → **Policies** → choose **Meena Iyer**, set **Deductible to 0**
   (keep 20% co-insurance, ₹500 copay) → **Issue policy**. With the default ₹5,000 deductible her ₹4,550 bill
   would be fully under the deductible and there would be nothing to claim.
2. Log in as **City Care**, upload `bill_04` for Meena again → now insurance pays **₹3,140** and Meena pays
   **₹1,410** (20% co-insurance ₹910 + ₹500 copay), and **File insurance claim** appears.
3. Back as **Suraksha** → **Claims queue** → open the claim → **Approve** (you can lower the amount) → **Mark settled**.
4. Log in as **City Care** → Overview: "Insurance settled" has increased.

---

## 6. Security checks (Member 4)

| Try this | Expected |
|---|---|
| Log in with a wrong password | "Incorrect email or password." |
| As Ramesh, open `http://localhost:3000/insurance` | Sent back to Ramesh's own overview |
| As Ramesh, open another patient's bill, e.g. `http://localhost:3000/bills/2` (Priya's) | "Bill not found." |
| Register a new account (patient / hospital / insurer) | Works; admin and finance cannot be self-registered |
| Insurer tries to settle a claim that is only "submitted" | Refused with a clear message |
| Open `http://localhost:8000/docs` → try `GET /api/dashboard/finance` without logging in | 401 Unauthorized |

---

## Re-running the checks yourself

```bash
# regenerate the images
backend/.venv/Scripts/python test_samples/make_samples.py

# run all samples through the real models inside the backend container (Git Bash: set MSYS_NO_PATHCONV=1 first)
docker compose cp test_samples backend:/srv/test_samples
docker compose exec backend python /srv/test_samples/evaluate_samples.py
```

---

## 7. Claim Decision Engine

Every claim now shows a **Recommended decision** for the insurer (claim page, claims list and insurer overview).
It combines the fraud risk (Member 2), the fair prices and duplicate detection (Member 3), and the policy terms:
duplicates are not paid, overpriced charges are paid only up to the fair price + 25%, and the policy is applied
again to the corrected bill.

| Sample | Suggested decision |
|---|---|
| bill_01 / bill_06 clean | **Approve in full** |
| bill_02 overcharged | **Approve a reduced amount** (room rent and MRI paid only up to fair price + 25%) |
| bill_03 duplicates | **Approve a reduced amount** (the two repeated lines are not paid) |
| bill_05 inflated cardiac | **Hold for investigation** (fraud risk HIGH) |
| Demo claim CLM-2026-00001 (Ramesh) | **Approve a reduced amount**: ₹76,719 instead of ₹91,356 |
| Demo claim CLM-2026-00003 (Priya) | **Reject: nothing payable** (after removing the overcharge and duplicate, the rest is under her deductible) |

Why a decision engine and not a trained model: Member 2's claim-approval model (`src/22_claim_approval_model.py`)
reaches 36% accuracy on three balanced classes (guessing gives 34%, ROC-AUC 0.54) because `ClaimStatus` in the
dataset is not related to any claim feature. The engine uses signals that really do decide payment.
