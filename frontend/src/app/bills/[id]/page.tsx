"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import AppShell from "@/components/AppShell";
import { SplitBar } from "@/components/charts";
import { Alert, ClaimStatusBadge, Kpi, Loading, PageHead, Panel, PaymentBadge, SeverityBadge, useApi } from "@/components/ui";
import { api, BillDetail, Claim, EMIPlan, User } from "@/lib/api";
import { date, inr, inrPaise, titleCase } from "@/lib/format";

const SPECIALTIES = ["General Practice", "Cardiology", "Neurology", "Orthopedics", "Pediatrics"];
const CLAIM_TYPES = ["Inpatient", "Outpatient", "Emergency", "Routine"];

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
  const canClaim = (user.role === "hospital" || user.role === "patient") && !bill.claim_id && bill.policy_id && bill.insurance_pays > 0;

  return (
    <>
      <PageHead title={bill.hospital_name || "Bill"}
        sub={`${bill.patient_name} · ${bill.bill_number ? `Bill ${bill.bill_number} · ` : ""}${bill.admission_date ? `${bill.admission_date} → ${bill.discharge_date} · ` : ""}analysed ${date(bill.created_at)} · ${titleCase(bill.city_tier)}, ${bill.hospital_type} pricing`}>
        <ClaimStatusBadge status={bill.claim_status} />
        <PaymentBadge status={bill.payment_status} />
        {bill.claim_id && <Link className="btn ghost small" href={`/claims/${bill.claim_id}`}>View claim</Link>}
      </PageHead>

      {bill.total_mismatch && <div style={{ marginBottom: 12 }}><Alert>The printed total ({inr(bill.stated_total)}) does not match the sum of the line items ({inr(bill.total_billed)}).</Alert></div>}

      <div className="kpis">
        <Kpi label="Total billed" value={inr(bill.total_billed)} sub={`${bill.items.length} line items · ${bill.source === "ocr" ? "read by OCR" : bill.source === "text" ? "parsed from text" : "entered manually"}`} />
        <Kpi label="Insurance pays" value={inr(bill.insurance_pays)} tone="good" />
        <Kpi label="Patient pays" value={inr(bill.patient_out_of_pocket)} tone="warn" />
        <Kpi label="Flagged for review" value={inr(bill.flagged_amount)} tone={bill.flagged_amount > 0 ? "bad" : undefined}
          sub={`${bill.duplicate_count} duplicate · ${bill.high_risk_count} overcharge`} />
      </div>

      <div className="stack">
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
          <Panel title="Who pays what" hint={bill.policy_id ? "Deductible → caps → co-insurance → copay" : "No active policy when this bill was analysed"}>
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
                <dt>Copay</dt><dd>{inrPaise(c.copay)}</dd>
                <dt className="total">Insurance pays</dt><dd className="total">{inrPaise(c.insurance_pays)}</dd>
                <dt className="total">Patient pays</dt><dd className="total">{inrPaise(c.patient_out_of_pocket)}</dd>
              </dl>
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
