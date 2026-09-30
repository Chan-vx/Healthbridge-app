# New test bills — patient upload

Seven new bills (not in the demo data or the first sample set). Every expected value
below comes from running these files through the real OCR and models.

## How to test each bill (as the patient)

1. Open **http://localhost:3000** and log in as the **patient** in the table (password `Demo@1234`).
2. **My bills** → tab **Upload image / PDF**.
3. **Hospital:** choose the hospital in the table (it must match the name on the bill — it sets the fair prices).
4. Choose the file → **Analyse bill**.
5. On the result page: check the line-item table, "Who pays what" and "How to pay the balance".
6. Click **File insurance claim** with the claim type and specialty listed → check the risk level.
7. Optional: in **EMI calculator**, choose a plan or pay in full.

| File | Log in as | Hospital to choose | Treatment |
|---|---|---|---|
| `new_bill_01_maternity_citycare.png` | priya@patient.in | City Care Multispeciality Hospital | Normal delivery |
| `new_bill_02_dengue_sunrise.png` | ramesh@patient.in | Sunrise General Hospital | Dengue admission |
| `new_bill_03_fracture_sunrise.png` | arjun@patient.in | Sunrise General Hospital | Leg fracture surgery |
| `new_bill_04_ent_no_insurance_citycare.png` | meena@patient.in | City Care Multispeciality Hospital | ENT visit (no insurance) |
| `new_bill_05_appendix_citycare.png` | priya@patient.in | City Care Multispeciality Hospital | Appendix surgery |
| `new_bill_06_spine_inflated_citycare.png` | arjun@patient.in | City Care Multispeciality Hospital | Spine surgery (inflated) |
| `new_bill_07_appendix_citycare.pdf` | priya@patient.in | City Care Multispeciality Hospital | Same as 05, as a PDF |

## Expected results

### new_bill_01 — maternity (everything fair)
- Total **₹76,760**, 6 items, all **Fair**, nothing flagged
- Insurance **₹60,084** · Priya pays **₹16,676** (₹10,000 deductible + 10% co-insurance ₹6,676)
- Top option: **Pay in Full (85)** — she earns ₹85,000/month
- Claim (Inpatient, General Practice): hybrid **0.120** → **LOW**

### new_bill_02 — dengue (duplicate + one line to review)
- Total **₹29,360**, 7 items
- **Duplicate:** "Blood Test Platelet Count" ≈ "Blood Test - Platelet Count" (**96.2%** similar)
- **Ultrasound Abdomen Scan** ₹7,500 vs fair ₹1,994 → **+276%, Review** (amber — the price is high but the anomaly model did not call it an outlier, so it is marked for review rather than "Overcharge")
- Flagged **₹2,000** (the duplicate line)
- Insurance **₹18,988** · Ramesh pays **₹10,372**
- Claim: hybrid **0.128** → **LOW**

### new_bill_03 — fracture (fair, with a non-covered item)
- Total **₹53,150**, 7 items, all **Fair**
- **Cosmetic hair spa (non-medical)** shows **Covered: No** — its ₹1,800 goes to the patient
- Insurance **₹45,215** · Arjun pays **₹7,935** (₹1,800 non-covered + 10% co-insurance ₹5,135 + ₹1,000 copay)
- Claim (Inpatient, **Orthopedics**): hybrid **0.112** → **LOW**

### new_bill_04 — ENT visit, no insurance
- Total **₹4,670**, 3 items, all **Fair**
- Insurance **₹0** · Meena pays **₹4,670** — she has no policy
- No **File insurance claim** button (correct)
- Top option: **Hospital No-Cost EMI (80)** — her income is ₹0, so paying in full cannot be assessed

### new_bill_05 — appendix surgery (room rent to review)
- Total **₹1,23,670**, 6 items
- **Room Rent (4 days)** ₹38,000 vs fair ₹19,920 → **+91%, Review**
- Everything else Fair (anaesthetist fee is below the generic procedure price, which is fine)
- Insurance **₹1,02,303** · Priya pays **₹21,367**
- Claim (**Emergency**, General Practice): hybrid **0.103** → **LOW**

### new_bill_06 — inflated spine surgery (HIGH fraud risk)
- Total **₹7,76,000**, 6 items
- **5 Overcharges:** room rent +105%, spine fusion +841%, ICU nursing +232%, MRI +733%, medicines +2160%
- Flagged **₹7,11,000**
- Insurance **₹6,47,900** · Arjun pays **₹1,28,100** (includes ₹55,000 above the ₹15,000 room-rent cap)
- Claim (Inpatient, **Orthopedics**): fraud probability **99.88%**, anomaly 0.567, hybrid **0.912** → **HIGH**, "Manual Investigation"
- Then log in as **claims@suraksha.in** → **Claims queue**: this claim is at the top; open it to see the SHAP reasons, then approve or reject

### new_bill_07 — the appendix bill as a PDF
- Exactly the same results as new_bill_05 — proves PDF upload works

## What these show in the viva

| Check | Shown by |
|---|---|
| OCR reads images and PDFs | all bills; 05 vs 07 |
| Fair price (Random Forest) | every line's "Fair price" column |
| Overcharge (Isolation Forest + ≥60% over fair price) | 06 |
| "Review" middle level | 02 (ultrasound), 05 (room rent) |
| Duplicate detection (text similarity ≥ 82%) | 02 |
| Non-covered items | 03 |
| Room-rent cap | 06 |
| No insurance | 04 |
| Deductible / co-insurance / copay split | 01, 03, 05 |
| Payment advice changes with income | 01 (Pay in Full) vs 04 (Hospital EMI) |
| Fraud engine LOW vs HIGH | 01–05 vs 06 |

Note: each upload is saved as a new bill, so uploading the same file twice creates two bills.

## Claim Decision Engine (insurer's "Recommended decision")

After you file each claim, log in as **claims@suraksha.in** and open it. The engine suggests:

| Bill | Suggested decision | Why |
|---|---|---|
| new_bill_01 maternity | **Approve in full** | All checks pass |
| new_bill_02 dengue | **Approve after verification** | Ultrasound is well above fair price (Review); duplicate platelet test is not paid |
| new_bill_03 fracture | **Approve in full** | All checks pass (the cosmetic item was never covered, so nothing extra is removed) |
| new_bill_04 ENT | — | No insurance, so no claim |
| new_bill_05 / 07 appendix | **Approve after verification** | Room rent is 91% above fair price (Review) |
| new_bill_06 spine | **Hold for investigation** | Fraud risk HIGH; the page also shows what would be payable if the claim is cleared |
