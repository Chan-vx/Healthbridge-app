"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useState } from "react";
import AppShell from "@/components/AppShell";
import { ShapBars } from "@/components/charts";
import { AdviceBadge, Alert, ClaimStatusBadge, Kpi, Loading, PageHead, Panel, RiskBadge, useApi } from "@/components/ui";
import { Advice, api, Claim, User } from "@/lib/api";
import { date, inr, titleCase } from "@/lib/format";

function Decision({ claim, onDone }: { claim: Claim; onDone: (c: Claim) => void }) {
  const [amount, setAmount] = useState(String(claim.advice?.recommended_amount ?? claim.claim_amount));
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function decide(action: "approve" | "reject" | "settle") {
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { action, note: note || undefined };
      if (action === "approve") body.approved_amount = Number(amount);
      onDone(await api<Claim>(`/api/claims/${claim.id}/decision`, { body }));
      setNote("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (claim.status === "rejected" || claim.status === "settled") return null;
  return (
    <Panel title="Decision" hint={claim.status === "submitted" ? (claim.advice ? `Recommended: ${claim.advice.label} (${inr(claim.advice.recommended_amount)})` : `Model recommendation: ${claim.recommendation}`) : "Approved and awaiting payment to the hospital."}>
      <div className="form">
        {claim.status === "submitted" && (
          <>
            <label className="field">Approved amount (₹)
              <input id="approved_amount" type="number" min={0} max={claim.claim_amount} value={amount} onChange={(e) => setAmount(e.target.value)} />
            </label>
            <label className="field">Note to hospital (optional)
              <textarea id="note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} style={{ fontFamily: "inherit" }} />
            </label>
          </>
        )}
        {error && <Alert>{error}</Alert>}
        <div className="btn-row">
          {claim.status === "submitted" ? (
            <>
              <button className="btn" disabled={busy} onClick={() => decide("approve")}>Approve</button>
              <button className="btn danger" disabled={busy} onClick={() => decide("reject")}>Reject</button>
            </>
          ) : (
            <button className="btn" disabled={busy} onClick={() => decide("settle")}>Mark settled ({inr(claim.approved_amount)})</button>
          )}
        </div>
      </div>
    </Panel>
  );
}

function AdvicePanel({ advice }: { advice: Advice }) {
  return (
    <Panel title="Recommended decision" hint={advice.method}>
      <div className="stack">
        <div className="btn-row" style={{ gap: 12 }}>
          <AdviceBadge decision={advice.decision} label={advice.label} />
          <span>{advice.summary}</span>
        </div>
        <dl className="kv" style={{ maxWidth: 480 }}>
          <dt>Claimed</dt><dd>{inr(advice.claimed_amount)}</dd>
          <dt>{advice.decision === "investigate" ? "Payable if cleared" : "Recommended to pay"}</dt><dd>{inr(advice.recommended_amount)}</dd>
          <dt className="total">Difference</dt><dd className="total">{inr(advice.saving)}</dd>
        </dl>
        {advice.bill_deductions.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Charge removed or reduced</th><th className="num">Billed</th><th className="num">Not paid</th><th>Reason</th></tr></thead>
              <tbody>
                {advice.bill_deductions.map((d) => (
                  <tr key={d.description}><td>{d.description}</td><td className="num">{inr(d.billed)}</td><td className="num">{inr(d.deducted)}</td><td className="muted">{d.reason}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="table-wrap">
          <table>
            <thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead>
            <tbody>
              {advice.checks.map((c) => (
                <tr key={c.name}>
                  <td>{c.name}</td>
                  <td>{c.ok ? <span className="badge b-good">Pass</span> : <span className="badge b-warn">Needs attention</span>}</td>
                  <td className="muted">{c.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="note-line" style={{ margin: 0 }}>
          Overpriced charges are paid up to the fair price + 25%, and duplicates are not paid. The policy terms are then
          applied again to the corrected bill. This is advice: the insurer makes the decision.
        </p>
      </div>
    </Panel>
  );
}

function ClaimView({ user }: { user: User }) {
  const { id } = useParams<{ id: string }>();
  const { data: claim, error, setData } = useApi<Claim>(`/api/claims/${id}`);
  if (!claim) return <Loading error={error} />;

  const tone = claim.risk_level === "HIGH" ? "bad" : claim.risk_level === "MEDIUM" ? "warn" : "good";
  const inputs = claim.model_inputs;

  return (
    <>
      <PageHead title={claim.claim_number}
        sub={`${claim.patient_name} · ${claim.hospital_name || "direct claim"} · ${claim.claim_type} · ${claim.provider_specialty} · submitted ${date(claim.submitted_at)}`}>
        <RiskBadge level={claim.risk_level} />
        <ClaimStatusBadge status={claim.status} />
        {claim.bill_id && <Link className="btn ghost small" href={`/bills/${claim.bill_id}`}>View bill</Link>}
      </PageHead>

      <div className="kpis">
        <Kpi label="Claimed" value={inr(claim.claim_amount)} sub={claim.approved_amount != null ? `Approved ${inr(claim.approved_amount)}` : undefined} />
        <Kpi label="Hybrid risk score" value={claim.hybrid_risk_score.toFixed(3)} tone={tone} sub={`${claim.risk_level} · ${claim.recommendation}`} />
        <Kpi label="XGBoost fraud probability" value={`${(claim.fraud_probability * 100).toFixed(2)}%`} sub={`Flag ${claim.fraud_prediction ? "raised" : "not raised"} at 5% threshold`} />
        <Kpi label="Isolation Forest anomaly" value={claim.anomaly_score.toFixed(3)} sub="0 = typical, 1 = most unusual" />
      </div>

      {claim.advice && <div style={{ marginBottom: 16 }}><AdvicePanel advice={claim.advice} /></div>}

      <div className="cols-2">
        <Panel title="Why the model scored it this way" hint="Top five SHAP factors from the XGBoost fraud model (log-odds units)">
          <ShapBars
            items={claim.top_factors.map((f) => ({ label: titleCase(f.feature), value: f.impact }))}
            format={(n) => n.toFixed(2)} upLabel="Increases fraud risk" downLabel="Decreases fraud risk" />
          <p className="note-line">Hybrid = 0.80 × {claim.fraud_probability.toFixed(4)} + 0.20 × {claim.anomaly_score.toFixed(4)} = {claim.hybrid_risk_score.toFixed(4)}. HIGH ≥ 0.70, MEDIUM ≥ 0.40.</p>
        </Panel>
        <div className="stack">
          {user.role === "insurer" && <Decision claim={claim} onDone={setData} />}
          {claim.decision_note && <Panel title="Decision note"><p style={{ margin: 0 }}>{claim.decision_note}</p><p className="note-line">{date(claim.decided_at)}</p></Panel>}
          <Panel title="What the fraud model saw" hint="Platform amounts are converted to the model's USD scale.">
            <dl className="kv">
              {Object.entries(inputs).map(([k, v]) => (
                <Fragment key={k}><dt>{k}</dt><dd>{typeof v === "number" ? v.toLocaleString("en-IN") : v}</dd></Fragment>
              ))}
            </dl>
          </Panel>
        </div>
      </div>
    </>
  );
}

export default function Page() {
  return <AppShell roles={["patient", "hospital", "insurer", "finance", "admin"]}>{(user) => <ClaimView user={user} />}</AppShell>;
}
