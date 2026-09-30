"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { ShapBars } from "@/components/charts";
import { ClaimStatusBadge, Empty, Kpi, Loading, PageHead, Panel, PaymentBadge, useApi } from "@/components/ui";
import { BillSummary, Claim, Policy, ShapItem } from "@/lib/api";
import { date, FEATURE_LABELS, inr, usd } from "@/lib/format";

interface PatientDash {
  bills: { count: number; total_billed: number; insurance_share: number; patient_share: number; flagged_amount: number; unpaid_patient_dues: number };
  claims: { count: number; by_status: Record<string, number> };
  active_policy: Policy | null;
  latest_estimate: { predicted_usd: number; predicted_inr: number; shap: ShapItem[]; created_at: string } | null;
  emi_monthly_total: number;
  recent_bills: BillSummary[];
  recent_claims: Claim[];
}

function Dashboard() {
  const router = useRouter();
  const { data, error } = useApi<PatientDash>("/api/dashboard/patient");
  if (!data) return <Loading error={error} />;
  const est = data.latest_estimate;
  const policy = data.active_policy;
  return (
    <>
      <PageHead title="Your health finances" sub="Estimates, bills, insurance cover and payments in one place.">
        <Link className="btn" href="/bills">Upload a bill</Link>
      </PageHead>
      <div className="kpis">
        <Kpi label="Predicted yearly cost" value={est ? usd(est.predicted_usd) : "—"} sub={est ? `≈ ${inr(est.predicted_inr)}` : "Run an estimate"} />
        <Kpi label="Total billed" value={inr(data.bills.total_billed)} sub={`${data.bills.count} bills`} />
        <Kpi label="Insurance covered" value={inr(data.bills.insurance_share)} tone="good" />
        <Kpi label="Unpaid dues" value={inr(data.bills.unpaid_patient_dues)} tone={data.bills.unpaid_patient_dues > 0 ? "warn" : undefined}
          sub={data.emi_monthly_total > 0 ? `EMI ${inr(data.emi_monthly_total)}/month` : undefined} />
        <Kpi label="Flagged charges" value={inr(data.bills.flagged_amount)} tone={data.bills.flagged_amount > 0 ? "bad" : undefined} sub="duplicates + overcharges" />
      </div>

      <div className="cols-2" style={{ marginBottom: 16 }}>
        <Panel title="What drives your cost estimate" hint="SHAP values from the cost prediction model"
          actions={<Link className="btn ghost small" href="/patient/estimate">Update estimate</Link>}>
          {est ? (
            <ShapBars
              items={est.shap.map((s) => ({ label: FEATURE_LABELS[s.feature] || s.feature, detail: String(s.value ?? ""), value: s.shap_usd }))}
              format={(n) => usd(n)} upLabel="Raises the estimate" downLabel="Lowers the estimate" />
          ) : (
            <Empty>No estimate yet. <Link href="/patient/estimate">Fill in your profile</Link> to get one.</Empty>
          )}
        </Panel>
        <Panel title="Insurance policy">
          {policy ? (
            <dl className="kv">
              <dt>Policy</dt><dd>{policy.policy_number}</dd>
              <dt>Insurer</dt><dd>{policy.insurer_name}</dd>
              <dt>Sum insured</dt><dd>{inr(policy.sum_insured)}</dd>
              <dt>Deductible</dt><dd>{inr(policy.deductible)}</dd>
              <dt>Co-insurance</dt><dd>{policy.co_insurance_pct}%</dd>
              <dt>Copay per bill</dt><dd>{inr(policy.copay_flat)}</dd>
              <dt>Room rent cap</dt><dd>{policy.room_rent_cap ? inr(policy.room_rent_cap) : "No cap"}</dd>
            </dl>
          ) : (
            <Empty>No active policy. Your insurer issues one from their HealthBridge workspace.</Empty>
          )}
        </Panel>
      </div>

      <Panel title="Recent bills" flush actions={<Link className="btn ghost small" href="/bills">All bills</Link>}>
        {data.recent_bills.length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Date</th><th>Hospital</th><th className="num">Billed</th><th className="num">Insurance</th><th className="num">You pay</th><th>Claim</th><th>Payment</th></tr></thead>
              <tbody>
                {data.recent_bills.map((b) => (
                  <tr key={b.id} className="clickable" onClick={() => router.push(`/bills/${b.id}`)}>
                    <td>{date(b.created_at)}</td>
                    <td>{b.hospital_name}</td>
                    <td className="num">{inr(b.total_billed)}</td>
                    <td className="num">{inr(b.insurance_pays)}</td>
                    <td className="num">{inr(b.patient_out_of_pocket)}</td>
                    <td><ClaimStatusBadge status={b.claim_status} /></td>
                    <td><PaymentBadge status={b.payment_status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty>No bills yet.</Empty>}
      </Panel>
    </>
  );
}

export default function Page() {
  return <AppShell roles={["patient"]}>{() => <Dashboard />}</AppShell>;
}
