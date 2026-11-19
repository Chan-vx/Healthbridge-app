"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import DeleteBill from "@/components/DeleteBill";
import { SplitBar } from "@/components/charts";
import {
  Alert, CheckBadge, ClaimStatusBadge, Kpi, Loading, PageHead, Panel, PaymentBadge, SeverityBadge, useApi, VerificationBadge,
} from "@/components/ui";
import { api, apiObjectUrl, BillDetail, Claim, EMIPlan, User } from "@/lib/api";
import { date, inr, inrPaise, titleCase } from "@/lib/format";

const SPECIALTIES = ["General Practice", "Cardiology", "Neurology", "Orthopedics", "Pediatrics"];
const CLAIM_TYPES = ["Inpatient", "Outpatient", "Emergency", "Routine"];
// the hospital submitted the bill or confirmed it: only these can be claimed
const CONFIRMED = ["hospital_uploaded", "confirmed"];
const DUPLICATE_CHECKS = ["duplicate_file", "duplicate_bill_number", "duplicate_content"];

function AuthenticityPanel({ bill }: { bill: BillDetail }) {
  const checks = bill.checks || [];
  return (
    <Panel title="Is this bill genuine?" flush actions={<CheckBadge status={bill.authenticity} />}
      hint="Checked against HealthBridge records and the uploaded file. Price checks are separate (below).">
      {checks.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead>
            <tbody>
              {checks.map((c) => (
                <tr key={c.key}><td>{c.name}</td><td><CheckBadge status={c.status} /></td><td className="muted">{c.detail}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <div className="panel-body muted">This bill was analysed before the authenticity checks were added.</div>}
    </Panel>
  );
}

const DIFF_LABEL: Record<string, string> = {
  amount: "Amount changed", missing: "Missing from this copy", added: "Not on the hospital's bill",
  total: "Total", date: "Date changed",
};

function show(value: number | string | null) {
  return value == null ? "—" : typeof value === "number" ? inr(value) : value;
}

/** The patient's copy next to the bill the hospital itself submitted under the same number. */
function RecordPanel({ bill }: { bill: BillDetail }) {
  const m = bill.match_result;
  const diffs = m?.differences || [];
  return (
    <Panel title="Compared with the hospital's record" flush
      hint={`Bill number read by OCR (${bill.bill_number}) looked up among the bills the hospital submitted; matched to its bill ${m?.record_number}.`}
      actions={<Link className="btn ghost small" href={`/bills/${bill.matched_bill_id}`}>Open hospital&apos;s record</Link>}>
      {diffs.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Line</th><th>Difference</th><th className="num">This copy</th><th className="num">Hospital&apos;s record</th></tr></thead>
            <tbody>
              {diffs.map((d, i) => (
                <tr key={i}>
                  <td>{d.description}</td><td><span className="badge b-bad">{DIFF_LABEL[d.kind] || d.kind}</span></td>
                  <td className="num">{show(d.copy)}</td><td className="num">{show(d.record)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <div className="panel-body muted">Every date, line and amount matches the hospital&apos;s record.</div>}
    </Panel>
  );
}

function ConfirmPanel({ bill, onDone }: { bill: BillDetail; onDone: (b: BillDetail) => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function decide(action: "confirm" | "dispute") {
    setBusy(true);
    setError(null);
    try {
      onDone(await api<BillDetail>(`/api/bills/${bill.id}/verification`, { body: { action, note: note || undefined } }));
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }
  return (
    <Panel title="Did your hospital issue this bill?"
      hint={`${bill.patient_name} uploaded it and named your hospital. Check it against your own billing records before it can be claimed.`}>
      <div className="form">
        <label className="field">Note (required if you dispute it)
          <textarea id="verify_note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} style={{ fontFamily: "inherit" }}
            placeholder="e.g. No admission for this patient on these dates" />
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="btn-row">
          <button className="btn" disabled={busy} onClick={() => decide("confirm")}>Confirm, this is our bill</button>
          <button className="btn danger" disabled={busy} onClick={() => decide("dispute")}>Dispute</button>
        </div>
      </div>
    </Panel>
  );
}

function ErrorLevelPanel({ bill }: { bill: BillDetail }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  async function load() {
    setError(null);
    try {
      setUrl(await apiObjectUrl(`/api/bills/${bill.id}/error-level`));
    } catch (err) {
      setError((err as Error).message);
    }
  }
  return (
    <Panel title="Error level analysis" actions={!url && <button className="btn ghost small" onClick={load}>Show</button>}
      hint="The photo re-saved as JPEG; brighter means it changed more.">
      {error && <Alert>{error}</Alert>}
      {url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt="Error level analysis of the bill photo" style={{ width: "100%", borderRadius: 6, border: "1px solid var(--line)" }} />
      ) : (
        <span className="muted small">
          Numbers pasted into a photo afterwards often glow brighter or rougher than the text around them. This is a picture for a
          person to judge, not an automatic result.
        </span>
      )}
    </Panel>
  );
}

function FileClaim({ bill, onDone }: { bill: BillDetail; onDone: (c: Claim) => void }) {
  const [form, setForm] = useState({ claim_type: "Inpatient", provider_specialty: "General Practice", submission_method: "Online" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onDone(await api<Claim>("/api/claims", { body: { bill_id: bill.id, ...form } }));
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }
  return (
    <Panel title="File insurance claim" hint={`Claims ${inr(bill.insurance_pays)} from the insurer. The fraud engine scores it on submission.`}>
      <form className="form" onSubmit={submit}>
        <div className="form-row">
          <label className="field">Claim type
            <select id="claim_type" value={form.claim_type} onChange={(e) => setForm({ ...form, claim_type: e.target.value })}>
              {CLAIM_TYPES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label className="field">Provider specialty
            <select id="specialty" value={form.provider_specialty} onChange={(e) => setForm({ ...form, provider_specialty: e.target.value })}>
              {SPECIALTIES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
        </div>
        {error && <Alert>{error}</Alert>}
        <div><button className="btn" disabled={busy}>{busy ? "Scoring…" : "Submit claim"}</button></div>
      </form>
    </Panel>
  );
}

function PayPanel({ bill, onDone }: { bill: BillDetail; onDone: (b: BillDetail) => void }) {
  const [rate, setRate] = useState(13.5);
  const [months, setMonths] = useState(12);
  const [preview, setPreview] = useState<EMIPlan | null>(bill.emi.plan || null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function recalc() {
    setError(null);
    try {
      setPreview(await api<EMIPlan>(`/api/bills/${bill.id}/emi`, { body: { annual_rate: rate, months } }));
    } catch (err) {
      setError((err as Error).message);
    }
  }
  async function pay(plan: "full" | "emi") {
    setBusy(true);
    setError(null);
    try {
      onDone(await api<BillDetail>(`/api/bills/${bill.id}/pay`, { body: { plan, annual_rate: rate, months } }));
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }
  return (
    <Panel title="EMI calculator" hint="EMI = P·r·(1+r)ⁿ / ((1+r)ⁿ − 1), r = annual rate ÷ 12 ÷ 100">
      <div className="form">
        <div className="form-row">
          <label className="field">Annual interest %<input id="rate" type="number" step="0.1" min={0} max={60} value={rate} onChange={(e) => setRate(Number(e.target.value))} /></label>
          <label className="field">Months<input id="months" type="number" min={1} max={120} value={months} onChange={(e) => setMonths(Number(e.target.value))} /></label>
          <div className="field" style={{ alignSelf: "end" }}><button type="button" className="btn ghost" onClick={recalc}>Recalculate</button></div>
        </div>
        {preview && (
          <dl className="kv">
            <dt>Principal</dt><dd>{inrPaise(preview.principal)}</dd>
            <dt>Monthly EMI</dt><dd>{inrPaise(preview.monthly_emi)}</dd>
            <dt>Total interest</dt><dd>{inrPaise(preview.total_interest)}</dd>
            <dt className="total">Total payable</dt><dd className="total">{inrPaise(preview.total_payment)}</dd>
          </dl>
        )}
        {error && <Alert>{error}</Alert>}
        {bill.payment_status === "unpaid" && (
          <div className="btn-row">
            <button className="btn" disabled={busy} onClick={() => pay("emi")}>Choose this EMI plan</button>
            <button className="btn ghost" disabled={busy} onClick={() => pay("full")}>Pay {inr(bill.patient_out_of_pocket)} in full</button>
          </div>
        )}
      </div>
    </Panel>
  );
}

function BillView({ user }: { user: User }) {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: bill, error, setData } = useApi<BillDetail>(`/api/bills/${id}`);
  const [showRaw, setShowRaw] = useState(false);
  if (!bill) return <Loading error={error} />;

  const c = bill.cost_breakdown as Record<string, number>;
  const dupes = bill.items.filter((i) => i.duplicate_of);
  const status = bill.verification_status || "hospital_uploaded";
  const repeat = (bill.checks || []).find((k) => DUPLICATE_CHECKS.includes(k.key) && k.status === "fail");
  const hospitalName = bill.registered_hospital || "The hospital";
  const insured = (user.role === "hospital" || user.role === "patient") && !bill.claim_id && bill.policy_id && bill.insurance_pays > 0;
  // a copy that matches the hospital's record is claimed here too; the claim is filed on that record
  const canClaim = insured && (CONFIRMED.includes(status) || status === "matched") && !repeat;

  return (
    <>
      <PageHead title={bill.registered_hospital || bill.hospital_name || "Bill"}
        sub={`${bill.patient_name} · ${bill.bill_number ? `Bill ${bill.bill_number} · ` : ""}${bill.admission_date ? `${bill.admission_date} → ${bill.discharge_date} · ` : ""}analysed ${date(bill.created_at)} · ${titleCase(bill.city_tier)}, ${bill.hospital_type} pricing`}>
        <VerificationBadge status={bill.verification_status} recordOnly={bill.record_only} />
        <ClaimStatusBadge status={bill.claim_status} />
        <PaymentBadge status={bill.payment_status} />
        {user.role === "patient" && <DeleteBill billId={bill.id} onDeleted={() => router.push("/bills")} />}
        {bill.claim_id && (user.role === "insurer" && ["submitted", "approved"].includes(bill.claim_status || "")
          ? <Link className="btn small" href={`/claims/${bill.claim_id}`}>{bill.claim_status === "submitted" ? "Decide on claim" : "Settle claim"}</Link>
          : <Link className="btn ghost small" href={`/claims/${bill.claim_id}`}>View claim</Link>)}
      </PageHead>

      <div className="stack" style={{ gap: 8, marginBottom: 12 }}>
        {bill.record_only && (
          <Alert kind="info">
            In your hospital&apos;s records only: {bill.patient_name} does not see this bill yet. It appears in their account when they
            upload a copy that matches it, or when a claim is filed on it.
          </Alert>
        )}
        {status === "pending" && user.role !== "hospital" && (
          <Alert kind="info">
            {user.role === "patient"
              ? `Waiting for ${hospitalName} to confirm this bill. You can file an insurance claim once they do.`
              : `Uploaded by the patient; ${hospitalName} has not confirmed it yet.`}
          </Alert>
        )}
        {status === "disputed" && (
          <Alert>{hospitalName} disputed this bill{bill.verification_note ? `: “${bill.verification_note}”` : "."} It cannot be claimed.</Alert>
        )}
        {status === "unverifiable" && (
          <Alert kind="info">No hospital on HealthBridge was chosen for this bill, so it cannot be confirmed or claimed.</Alert>
        )}
        {status === "confirmed" && bill.verified_at && (
          <Alert kind="ok">{hospitalName} confirmed this bill on {date(bill.verified_at)}.</Alert>
        )}
        {status === "matched" && bill.matched_bill_id && (
          <Alert kind="ok">
            This is a copy of bill {bill.match_result?.record_number} that {hospitalName} submitted itself, and it matches
            exactly, so it is genuine. {bill.claim_id ? "The insurance claim for this bill is on the hospital's record." : "You can file the insurance claim below; it is filed on the hospital's record, so the bill is never claimed twice."}{" "}
            <Link href={`/bills/${bill.matched_bill_id}`}>Open the hospital&apos;s record</Link>
          </Alert>
        )}
        {status === "mismatch" && (
          <Alert>
            This copy differs from {hospitalName}&apos;s own record of bill {bill.match_result?.record_number} in{" "}
            {bill.match_result?.differences?.length} place(s), so it cannot be claimed. See the comparison below.
          </Alert>
        )}
        {repeat && <Alert>This bill repeats an earlier one and cannot be claimed: {repeat.detail}</Alert>}
        {bill.total_mismatch && <Alert>The printed total ({inr(bill.stated_total)}) does not match the sum of the line items ({inr(bill.total_billed)}).</Alert>}
      </div>

      {user.role === "hospital" && status === "pending" && <div style={{ marginBottom: 16 }}><ConfirmPanel bill={bill} onDone={setData} /></div>}

      <div className="kpis">
        <Kpi label="Total billed" value={inr(bill.total_billed)} sub={`${bill.items.length} line items · ${bill.source === "ocr" ? "read by OCR" : bill.source === "text" ? "parsed from text" : "entered manually"}`} />
        <Kpi label="Insurance pays" value={inr(bill.insurance_pays)} tone="good" />
        <Kpi label="Patient pays" value={inr(bill.patient_out_of_pocket)} tone="warn" />
        <Kpi label="Flagged for review" value={inr(bill.flagged_amount)} tone={bill.flagged_amount > 0 ? "bad" : undefined}
          sub={`${bill.duplicate_count} duplicate · ${bill.high_risk_count} overcharge`} />
      </div>

      <div className="stack">
        <AuthenticityPanel bill={bill} />
        {bill.matched_bill_id && <RecordPanel bill={bill} />}

        <Panel title="Line-item check" flush
          hint="Fair price from the Random Forest model; anomaly flag from the Isolation Forest; duplicates by text similarity ≥ 82%.">
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Item</th><th>Category</th><th className="num">Qty</th><th className="num">Billed</th><th className="num">Fair price</th><th className="num">Difference</th><th>Check</th><th>Covered</th></tr>
              </thead>
              <tbody>
                {bill.items.map((i) => (
                  <tr key={i.id}>
                    <td>
                      {i.description}
                      {i.duplicate_of && <div className="small" style={{ color: "var(--bad)" }}>Possible duplicate of “{i.duplicate_of}” ({i.duplicate_similarity}% similar)</div>}
                    </td>
                    <td className="muted">{titleCase(i.category)}</td>
                    <td className="num">{i.quantity}</td>
                    <td className="num">{inr(i.amount)}</td>
                    <td className="num">{inr(i.fair_price)}</td>
                    <td className="num" style={{ color: (i.overcharge_pct ?? 0) >= 25 ? "var(--bad)" : "var(--muted)" }}>
                      {i.overcharge_pct == null ? "—" : `${i.overcharge_pct > 0 ? "+" : ""}${i.overcharge_pct.toFixed(1)}%`}
                    </td>
                    <td>{i.duplicate_of ? <span className="badge b-bad">Duplicate</span> : <SeverityBadge severity={i.severity} />}</td>
                    <td>{i.is_covered ? "Yes" : <span className="muted">No</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <div className="cols-2">
          <Panel title="Who pays what" hint={bill.policy_id ? "Caps → deductible → co-insurance → sum insured left this year → copay" : "No active policy when this bill was analysed"}>
            <div className="stack">
              <SplitBar parts={[
                { label: "Insurance", value: bill.insurance_pays, color: "var(--chart-1)", text: inr(bill.insurance_pays) },
                { label: "Patient", value: bill.patient_out_of_pocket, color: "var(--chart-2)", text: inr(bill.patient_out_of_pocket) },
              ]} />
              <dl className="kv">
                <dt>Total billed</dt><dd>{inrPaise(c.total_billed)}</dd>
                <dt>Not covered (e.g. cosmetic)</dt><dd>{inrPaise(c.non_covered_amount)}</dd>
                <dt>Above category caps</dt><dd>{inrPaise(c.category_cap_deductions)}</dd>
                <dt>Covered amount</dt><dd>{inrPaise(c.covered_amount)}</dd>
                <dt>Deductible</dt><dd>{inrPaise(c.deductible_applied)}</dd>
                <dt>Co-insurance (patient share)</dt><dd>{inrPaise(c.co_insurance_patient_share)}</dd>
                {c.sum_insured_shortfall > 0 && <><dt>Above the sum insured left this year</dt><dd>{inrPaise(c.sum_insured_shortfall)}</dd></>}
                <dt>Copay</dt><dd>{inrPaise(c.copay)}</dd>
                <dt className="total">Insurance pays</dt><dd className="total">{inrPaise(c.insurance_pays)}</dd>
                <dt className="total">Patient pays</dt><dd className="total">{inrPaise(c.patient_out_of_pocket)}</dd>
              </dl>
              {user.role === "patient" && bill.policy_id && (
                <p className="note-line" style={{ margin: 0 }}>
                  How each step is decided: <Link href="/patient/insurance#terms">your plan&apos;s terms and conditions</Link>.
                </p>
              )}
            </div>
          </Panel>

          <Panel title="How to pay the balance" hint="Ranked by the recommendation engine (0–100 suitability)" flush>
            {bill.recommendations.length ? bill.recommendations.map((r) => (
              <div className="rec" key={r.option}>
                <div className="score">{Math.round(r.suitability_score)}</div>
                <div><div className="title">{r.option}</div><p>{r.reasoning}</p></div>
              </div>
            )) : <div className="panel-body muted">Nothing is owed on this bill.</div>}
          </Panel>
        </div>

        <div className="cols-2">
          {user.role === "patient" && bill.patient_out_of_pocket > 0 && (
            bill.payment ? (
              <Panel title="Your payment plan">
                <dl className="kv">
                  <dt>Plan</dt><dd>{bill.payment.plan === "emi" ? `EMI · ${bill.payment.tenure_months} months @ ${bill.payment.annual_rate}%` : "Paid in full"}</dd>
                  <dt>Monthly</dt><dd>{inrPaise(bill.payment.monthly_emi)}</dd>
                  <dt className="total">Total</dt><dd className="total">{inrPaise(bill.payment.total_payment)}</dd>
                </dl>
              </Panel>
            ) : <PayPanel bill={bill} onDone={setData} />
          )}
          {canClaim && <FileClaim bill={bill} onDone={(claim) => router.push(`/claims/${claim.id}`)} />}
          {bill.raw_text && (
            <Panel title="OCR text" actions={<button className="btn ghost small" onClick={() => setShowRaw(!showRaw)}>{showRaw ? "Hide" : "Show"}</button>}>
              {showRaw ? <pre className="raw">{bill.raw_text}</pre> : <span className="muted small">The text Tesseract read from the bill, before parsing.</span>}
            </Panel>
          )}
          {bill.error_level_available && user.role !== "patient" && <ErrorLevelPanel bill={bill} />}
        </div>
        {dupes.length > 0 && user.role !== "patient" && (
          <p className="note-line">Duplicate lines are counted in the flagged amount; they are not removed from the bill automatically.</p>
        )}
      </div>
    </>
  );
}

export default function Page() {
  return <AppShell roles={["patient", "hospital", "insurer", "finance", "admin"]}>{(user) => <BillView user={user} />}</AppShell>;
}
