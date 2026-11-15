# Fake bills — testing the authenticity checks

Every price on these bills is **fair**, so the price checks (fair-price model, anomaly model,
duplicate lines) find nothing wrong. They test the other question: *is this a real bill from
this hospital for this patient?* Every expected value below comes from uploading these files
through the real OCR. Start from fresh demo data (`docker compose down -v`, then
`docker compose up --build`); every password is `Demo@1234`.

## How the app decides whether a bill is genuine

1. **Compared with the hospital's own record.** When a **patient** uploads a bill, OCR reads its
   bill number and the app looks for the bill the **hospital itself** submitted under that number
   (tolerating OCR misreads such as O for 0). If it finds it, it compares the two date by date and
   line by line:
   - everything the same → **Matches hospital record**: genuine. The claim is filed on the
     hospital's record, so the same bill is never claimed or counted twice;
   - anything different → **Differs from hospital record**, with every difference listed
     ("₹86,000 on this copy vs ₹36,000 in the hospital's record"). It cannot be claimed;
   - the number belongs to **another patient's** bill → the upload is **refused**, without showing that bill.
2. **Hospital confirmation** when the hospital has not submitted the bill (yet): the bill waits
   until the hospital presses **Confirm** or **Dispute**. If the hospital submits the bill later,
   the waiting copy is compared automatically.
3. **Seven automatic checks**, shown under **"Is this bill genuine?"**:

   | Check | Fails when |
   |---|---|
   | Hospital name | the name printed on the bill does not match the hospital it was filed under |
   | Patient name | the name printed on the bill is clearly someone else's: the upload is **refused** and nothing is saved (small OCR slips such as "lyer" for "Iyer" pass) |
   | File not uploaded before | exactly the same file was submitted before (SHA-256 fingerprint) |
   | Bill number not used before | this hospital already has another bill with that number |
   | Not a copy of another bill | same hospital, dates, lines and amounts as an earlier bill (catches re-photographed or re-typed copies) |
   | Treatment dates | discharge before admission, or a date in the future. **Warning** if the treatment is before the policy started or over a year old |
   | No signs of editing | **Warning** if the file's metadata names editing software (Photoshop, Canva, iLovePDF …), or a PDF was modified or saved again after it was made |

   A failed check makes the insurer's **Recommended decision** "Hold for investigation"; a
   warning makes it "Approve after verification". A repeated bill cannot be claimed at all.
4. **Error level analysis** (JPEG photos only): hospital, insurer and finance users can press
   **Show** to see where a photo was changed. It is a picture for a person to judge, not a score.

The demo data holds the hospitals' own records of `fake_06` (Sunrise, ₹36,000 surgery) and of the
genuine copy below, plus Ramesh's real bill CCH-2026-00891 that `fake_03` borrows the number of.

## The bills

Upload each one **as the patient** (My bills → Upload image / PDF → choose the hospital → the file).

| File | Log in as | Hospital to choose | What it is |
|---|---|---|---|
| `../patient_copies/copy_01_genuine_priya_citycare.png` | priya@patient.in | City Care Multispeciality Hospital | **Genuine** copy of City Care's bill CCH-2026-02350 |
| `fake_01_wrong_hospital.png` | priya@patient.in | City Care Multispeciality Hospital | Bill printed by "Greenleaf Medical Centre" |
| `fake_02_wrong_patient.png` | priya@patient.in | City Care Multispeciality Hospital | Someone else's bill (Rahul Verma) |
| `fake_03_reused_bill_number.png` | ramesh@patient.in | City Care Multispeciality Hospital | Made-up bill using the number of Ramesh's real bill CCH-2026-00891 |
| `fake_04_impossible_dates.png` | arjun@patient.in | Sunrise General Hospital | Discharged 26-Oct, admitted 30-Oct |
| `fake_05_photoshop_metadata.jpg` | priya@patient.in | City Care Multispeciality Hospital | Photo saved by Photoshop |
| `fake_06_pasted_amount.jpg` | arjun@patient.in | Sunrise General Hospital | Real Sunrise bill with the surgery amount and total pasted over (₹36,000 → ₹86,000) |
| `fake_07_edited_pdf.pdf` | ramesh@patient.in | Sunrise General Hospital | PDF re-saved by iLovePDF two days after it was made |
| any bill, **twice** | e.g. priya, `../new_bills/new_bill_01_maternity_citycare.png` | City Care | The same bill submitted again |

## Expected results

| File | Badge | What the bill page says |
|---|---|---|
| copy_01 (genuine) | **Matches hospital record** | All checks **Pass**. "Compared with the hospital's record": every date, line and amount matches. Banner: *open the hospital's record to file the claim there* |
| fake_01 | Awaiting hospital | **Fail** — Hospital name: Bill says "GREENLEAF MEDICAL CENTRE"; filed under "City Care Multispeciality Hospital" (34% match) |
| fake_02 | — (not saved) | **Refused at upload**: *This bill is for "Rahul Verma", not Priya Sharma. You can only add bills issued to you.* Nothing is added to her account |
| fake_03 | **Differs from hospital record** | **Fail** — 14 differences from City Care's own bill CCH-2026-00891 (dates and every line) |
| fake_04 | Awaiting hospital | **Fail** — Treatment dates: Discharge (26 Oct 2026) is before admission (30 Oct 2026) |
| fake_05 | Awaiting hospital | **Warning** — the file's metadata says it was saved by editing software (Photoshop) |
| fake_06 | **Differs from hospital record** | **Fail** — Surgery - Hernia Repair: **₹86,000 on this copy vs ₹36,000** in the hospital's record; total of the lines differs too. (Error level analysis also shows the pasted numbers glowing) |
| fake_07 | Awaiting hospital | **Warning** — The PDF was produced or edited with iLovePDF. The PDF was modified after it was first created |
| a bill uploaded twice | — | **Fail** ×3 — same file, bill number already used, same lines and amounts |

Bills marked *Awaiting hospital* have no hospital record to compare with, so the check
"Matches the hospital's record" shows **Waiting**. Then:

1. Log in as the hospital (City Care = `citycare@hospital.in`, Sunrise = `sunrise@hospital.in`).
   The overview lists **"Bills patients uploaded: awaiting your confirmation"** and
   **"Patient copies that differ from your bills"**.
2. Open a fake → **Dispute** with a note (e.g. "No admission for this patient on these dates").
   The patient sees *"City Care disputed this bill"* and it can never be claimed.
3. Open a genuine one (e.g. `new_bill_01`) → **Confirm, this is our bill** → the patient can now
   file the claim, and the insurer's recommendation is **Approve in full**.

**Record arriving later:** as Sunrise, upload a bill for a patient who already uploaded their copy
(e.g. Arjun uploads `../new_bills/new_bill_03_fracture_sunrise.png` first, then Sunrise uploads the
same file for Arjun). Arjun's copy changes from *Awaiting hospital* to **Matches hospital record**
by itself.

The demo data also has a bill Arjun uploaded that is **awaiting** Sunrise, and a bill Priya
uploaded that City Care **disputed**.

## For the viva

- Prices and fraud risk are judged by the ML models; **authenticity** is judged against records,
  because a fake bill with fair prices looks normal to any price model.
- OCR (the AI part) reads the bill number; the app then **reconciles** the patient's copy against
  the hospital's own record. A changed amount is found line by line, however well it was edited.
- Without a hospital record, the hospital confirms by hand. The same principle applies in real
  cashless claims, where the hospital (not the patient) sends the bill to the insurer.
- Tampering signs are **warnings, not proof**: metadata can be stripped (fake_06 has none). The
  record comparison is what catches it.
- In production, hospitals would send every bill digitally and signed (India's NHCX claims
  exchange), so every patient copy would have a record to compare with.

To regenerate the files: `python test_samples/make_fake_samples.py` (it reuses `make_samples.py`'s layout).
