"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { MonthlyRiskChart } from "@/components/charts";
import { AdviceBadge, Empty, Kpi, Loading, PageHead, Panel, RiskBadge, useApi } from "@/components/ui";
import { Claim } from "@/lib/api";
import { date, inr, titleCase } from "@/lib/format";

interface InsurerDash {
  insurer: { name: string };
  active_policies: number;
  claims: {
    count: number; by_status: Record<string, number>; by_risk: Record<string, number>; claimed_amount: number;
    approved_amount: number; settled_amount: number; approval_rate: number | null; fraud_flagged: number; avg_hybrid_risk: number | null;
  };
  monthly: { month: string; HIGH: number; MEDIUM: number; LOW: number }[];
  provider_risk: { provider: string; claims: number; high_risk: number; avg_hybrid_risk: number; claimed: number }[];
  top_risk_factors: { feature: string; claims: number }[];
  queue: Claim[];
}

function Dashboard() {
  const router = useRouter();
  const { data, error } = useApi<InsurerDash>("/api/dashboard/insurer");
  if (!data) return <Loading error={error} />;
  const c = data.claims;
  return (
    <>
      <PageHead title={data.insurer.name} sub="Claims are scored by XGBoost and Isolation Forest when they arrive; high-risk claims go to the top of the queue.">
        <Link className="btn" href="/insurance/policies">Issue a policy</Link>
      </PageHead>
      <div className="kpis">
        <Kpi label="Claims received" value={c.count} sub={`${data.active_policies} active policies`} />
        <Kpi label="Awaiting decision" value={c.by_status.submitted} tone={c.by_status.submitted ? "warn" : undefined} />
        <Kpi label="High-risk claims" value={c.by_risk.HIGH} tone={c.by_risk.HIGH ? "bad" : undefined} sub={`${c.fraud_flagged} over the 5% fraud threshold`} />
        <Kpi label="Approved" value={inr(c.approved_amount)} sub={c.approval_rate == null ? undefined : `${Math.round(c.approval_rate * 100)}% approval rate`} />
        <Kpi label="Settled" value={inr(c.settled_amount)} tone="good" sub={`of ${inr(c.claimed_amount)} claimed`} />
      </div>

      <div className="stack">
        <Panel title="Investigation queue" flush hint="Open claims, highest hybrid risk first" actions={<Link className="btn ghost small" href="/claims">Full queue</Link>}>
          {data.queue.length ? (
            <div className="table-wrap"><table>
              <thead><tr><th>Claim</th><th>Submitted</th><th>Patient</th><th>Hospital</th><th className="num">Amount</th><th className="num">Hybrid</th><th>Risk</th><th>Suggested decision</th><th className="num">Suggested pay</th></tr></thead>
              <tbody>{data.queue.map((q) => (
                <tr key={q.id} className="clickable" onClick={() => router.push(`/claims/${q.id}`)}>
                  <td className="mono">{q.claim_number}</td><td>{date(q.submitted_at)}</td><td>{q.patient_name}</td><td>{q.hospital_name || "—"}</td>
                  <td className="num">{inr(q.claim_amount)}</td><td className="num">{q.hybrid_risk_score.toFixed(3)}</td>
                  <td><RiskBadge level={q.risk_level} /></td>
                  <td>{q.advice ? <AdviceBadge decision={q.advice.decision} label={q.advice.label} /> : q.recommendation}</td>
                  <td className="num">{!q.advice ? "—" : q.advice.decision === "investigate" ? "On hold" : inr(q.advice.recommended_amount)}</td>
                </tr>))}
              </tbody>
            </table></div>
          ) : <Empty>No claims are waiting for a decision.</Empty>}
        </Panel>

        <div className="cols-2">
          <Panel title="Claims by month and risk level">
            {data.monthly.length ? <MonthlyRiskChart rows={data.monthly} /> : <Empty>No claims yet.</Empty>}
          </Panel>
          <Panel title="Provider risk" flush hint="Average hybrid score of each hospital's claims">
            {data.provider_risk.length ? (
              <div className="table-wrap"><table>
                <thead><tr><th>Provider</th><th className="num">Claims</th><th className="num">High risk</th><th className="num">Avg hybrid</th><th className="num">Claimed</th></tr></thead>
                <tbody>{data.provider_risk.map((p) => (
                  <tr key={p.provider}><td>{p.provider}</td><td className="num">{p.claims}</td><td className="num">{p.high_risk}</td>
                    <td className="num">{p.avg_hybrid_risk.toFixed(3)}</td><td className="num">{inr(p.claimed)}</td></tr>))}
                </tbody>
              </table></div>
            ) : <Empty>No claims yet.</Empty>}
            {data.top_risk_factors.length > 0 && (
              <div className="panel-body" style={{ borderTop: "1px solid var(--line)" }}>
                <h3 style={{ marginBottom: 6 }}>Factors most often raising risk</h3>
                <div className="btn-row">{data.top_risk_factors.map((f) => (
                  <span key={f.feature} className="badge b-muted">{titleCase(f.feature)} · {f.claims}</span>))}
                </div>
              </div>
            )}
          </Panel>
        </div>
      </div>
    </>
  );
}

export default function Page() {
  return <AppShell roles={["insurer"]}>{() => <Dashboard />}</AppShell>;
}
