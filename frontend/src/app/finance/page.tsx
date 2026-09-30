"use client";

import AppShell from "@/components/AppShell";
import { MonthlyRiskChart, MonthlyShareChart, SplitBar } from "@/components/charts";
import { Empty, Kpi, Loading, PageHead, Panel, useApi } from "@/components/ui";
import { inr } from "@/lib/format";

interface FinanceDash {
  bills: { count: number; total_billed: number; insurance_share: number; patient_share: number; flagged_amount: number; duplicates: number; high_risk_items: number; unpaid_patient_dues: number };
  claims: { count: number; by_status: Record<string, number>; claimed_amount: number; approved_amount: number; settled_amount: number; approval_rate: number | null };
  payments: { paid_in_full: number; on_emi_principal: number; emi_plans: number; emi_interest: number; emi_monthly_inflow: number };
  monthly: { month: string; billed: number; insurance: number; patient: number; flagged: number }[];
  claims_monthly: { month: string; HIGH: number; MEDIUM: number; LOW: number }[];
  per_hospital: { hospital: string; bills: number; billed: number; insurance: number; patient: number; flagged: number; claims: number; avg_hybrid_risk: number | null }[];
  top_recommendations: { option: string; bills: number }[];
}

function Dashboard() {
  const { data, error } = useApi<FinanceDash>("/api/dashboard/finance");
  if (!data) return <Loading error={error} />;
  const b = data.bills, c = data.claims, p = data.payments;
  const claimsOpen = c.claimed_amount - c.approved_amount;
  return (
    <>
      <PageHead title="Financial overview" sub="Platform-wide billing, insurance settlement and patient payment figures." />
      <div className="kpis">
        <Kpi label="Total billed" value={inr(b.total_billed)} sub={`${b.count} bills`} />
        <Kpi label="Insurance share" value={inr(b.insurance_share)} sub={`${Math.round((b.insurance_share / (b.total_billed || 1)) * 100)}% of billing`} />
        <Kpi label="Patient share" value={inr(b.patient_share)} sub={`${inr(b.unpaid_patient_dues)} still unpaid`} tone={b.unpaid_patient_dues > 0 ? "warn" : undefined} />
        <Kpi label="Claims settled" value={inr(c.settled_amount)} tone="good" sub={`${inr(c.approved_amount - c.settled_amount)} approved, awaiting payment`} />
        <Kpi label="Overcharges caught" value={inr(b.flagged_amount)} tone={b.flagged_amount ? "bad" : undefined} sub={`${b.duplicates} duplicates · ${b.high_risk_items} overpriced lines`} />
      </div>

      <div className="stack">
        <div className="cols-3">
          <Panel title="Monthly billing by payer">
            {data.monthly.length ? <MonthlyShareChart rows={data.monthly} /> : <Empty>No bills yet.</Empty>}
          </Panel>
          <Panel title="Where claimed money stands">
            <div className="stack">
              <SplitBar parts={[
                { label: "Settled", value: c.settled_amount, color: "var(--chart-3)", text: inr(c.settled_amount) },
                { label: "Approved", value: c.approved_amount - c.settled_amount, color: "var(--chart-1)", text: inr(c.approved_amount - c.settled_amount) },
                { label: "Pending or rejected", value: claimsOpen, color: "var(--chart-2)", text: inr(claimsOpen) },
              ]} />
              <dl className="kv">
                <dt>Paid in full by patients</dt><dd>{inr(p.paid_in_full)}</dd>
                <dt>Financed on EMI</dt><dd>{inr(p.on_emi_principal)}</dd>
                <dt>EMI plans</dt><dd>{p.emi_plans}</dd>
                <dt>EMI interest to lenders</dt><dd>{inr(p.emi_interest)}</dd>
                <dt>EMI inflow per month</dt><dd>{inr(p.emi_monthly_inflow)}</dd>
              </dl>
            </div>
          </Panel>
        </div>

        <Panel title="By hospital" flush>
          {data.per_hospital.length ? (
            <div className="table-wrap"><table>
              <thead><tr><th>Hospital</th><th className="num">Bills</th><th className="num">Billed</th><th className="num">Insurance</th><th className="num">Patients</th><th className="num">Flagged</th><th className="num">Claims</th><th className="num">Avg hybrid risk</th></tr></thead>
              <tbody>{data.per_hospital.map((h) => (
                <tr key={h.hospital}>
                  <td>{h.hospital}</td><td className="num">{h.bills}</td><td className="num">{inr(h.billed)}</td><td className="num">{inr(h.insurance)}</td>
                  <td className="num">{inr(h.patient)}</td><td className="num" style={{ color: h.flagged ? "var(--bad)" : undefined }}>{inr(h.flagged)}</td>
                  <td className="num">{h.claims}</td><td className="num">{h.avg_hybrid_risk == null ? "—" : h.avg_hybrid_risk.toFixed(3)}</td>
                </tr>))}
              </tbody>
            </table></div>
          ) : <Empty>No data yet.</Empty>}
        </Panel>

        <div className="cols-2">
          <Panel title="Claims by month and risk level">
            {data.claims_monthly.length ? <MonthlyRiskChart rows={data.claims_monthly} /> : <Empty>No claims yet.</Empty>}
          </Panel>
          <Panel title="Top financing recommendation per bill" flush>
            {data.top_recommendations.length ? (
              <div className="table-wrap"><table>
                <thead><tr><th>Recommended option</th><th className="num">Bills</th></tr></thead>
                <tbody>{data.top_recommendations.map((r) => <tr key={r.option}><td>{r.option}</td><td className="num">{r.bills}</td></tr>)}</tbody>
              </table></div>
            ) : <Empty>No bills with a balance yet.</Empty>}
          </Panel>
        </div>
      </div>
    </>
  );
}

export default function Page() {
  return <AppShell roles={["finance", "admin"]}>{() => <Dashboard />}</AppShell>;
}
