"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { MonthlyShareChart } from "@/components/charts";
import { ClaimStatusBadge, Empty, Kpi, Loading, PageHead, Panel, RiskBadge, useApi } from "@/components/ui";
import { BillSummary, Claim } from "@/lib/api";
import { date, inr } from "@/lib/format";

interface HospitalDash {
  hospital: { name: string; city: string; city_tier: string; hospital_type: string };
  bills: { count: number; total_billed: number; flagged_amount: number; duplicates: number; high_risk_items: number };
  claims: { count: number; by_status: Record<string, number>; by_risk: Record<string, number>; approval_rate: number | null };
  revenue: { billed: number; insurance_receivable: number; insurance_settled: number; insurance_pending: number; patient_collected: number; patient_outstanding: number };
  monthly: { month: string; insurance: number; patient: number; billed: number }[];
  unclaimed_bills: BillSummary[];
  recent_claims: Claim[];
}

function Dashboard() {
  const router = useRouter();
  const { data, error } = useApi<HospitalDash>("/api/dashboard/hospital");
  if (!data) return <Loading error={error} />;
  const r = data.revenue;
  return (
    <>
      <PageHead title={data.hospital.name} sub={`${data.hospital.city} · ${data.hospital.city_tier} · ${data.hospital.hospital_type}`}>
        <Link className="btn" href="/bills">Upload a bill</Link>
      </PageHead>
      <div className="kpis">
        <Kpi label="Revenue billed" value={inr(r.billed)} sub={`${data.bills.count} bills`} />
        <Kpi label="Insurance settled" value={inr(r.insurance_settled)} tone="good" />
        <Kpi label="Insurance receivable" value={inr(r.insurance_receivable)} sub="approved, not yet paid" />
        <Kpi label="Claims pending review" value={inr(r.insurance_pending)} sub={`${data.claims.by_status.submitted} claims`} />
        <Kpi label="Patient dues outstanding" value={inr(r.patient_outstanding)} tone={r.patient_outstanding > 0 ? "warn" : undefined} sub={`${inr(r.patient_collected)} collected or on EMI`} />
      </div>
      <div className="cols-3" style={{ marginBottom: 16 }}>
        <Panel title="Monthly billing" hint="Split between insurers and patients">
          {data.monthly.length ? <MonthlyShareChart rows={data.monthly} /> : <Empty>No bills yet.</Empty>}
        </Panel>
        <Panel title="Billing quality" hint="Found by the bill analyzer before claims go out">
          <dl className="kv">
            <dt>Duplicate lines</dt><dd>{data.bills.duplicates}</dd>
            <dt>Overcharged lines</dt><dd>{data.bills.high_risk_items}</dd>
            <dt>Amount flagged</dt><dd>{inr(data.bills.flagged_amount)}</dd>
            <dt>Claims filed</dt><dd>{data.claims.count}</dd>
            <dt>High-risk claims</dt><dd>{data.claims.by_risk.HIGH}</dd>
            <dt>Approval rate</dt><dd>{data.claims.approval_rate == null ? "—" : `${Math.round(data.claims.approval_rate * 100)}%`}</dd>
          </dl>
        </Panel>
      </div>
      <div className="cols-2">
        <Panel title="Bills ready to claim" flush hint="Insured bills without a claim">
          {data.unclaimed_bills.length ? (
            <div className="table-wrap"><table>
              <thead><tr><th>Date</th><th>Patient</th><th className="num">Insurance share</th><th /></tr></thead>
              <tbody>{data.unclaimed_bills.map((b) => (
                <tr key={b.id} className="clickable" onClick={() => router.push(`/bills/${b.id}`)}>
                  <td>{date(b.created_at)}</td><td>{b.patient_name}</td><td className="num">{inr(b.insurance_pays)}</td>
                  <td><span className="btn ghost small">File claim</span></td>
                </tr>))}
              </tbody>
            </table></div>
          ) : <Empty>Every insured bill has a claim.</Empty>}
        </Panel>
        <Panel title="Recent claims" flush actions={<Link className="btn ghost small" href="/claims">All claims</Link>}>
          {data.recent_claims.length ? (
            <div className="table-wrap"><table>
              <thead><tr><th>Claim</th><th>Patient</th><th className="num">Amount</th><th>Risk</th><th>Status</th></tr></thead>
              <tbody>{data.recent_claims.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => router.push(`/claims/${c.id}`)}>
                  <td className="mono">{c.claim_number}</td><td>{c.patient_name}</td><td className="num">{inr(c.claim_amount)}</td>
                  <td><RiskBadge level={c.risk_level} /></td><td><ClaimStatusBadge status={c.status} /></td>
                </tr>))}
              </tbody>
            </table></div>
          ) : <Empty>No claims yet.</Empty>}
        </Panel>
      </div>
    </>
  );
}

export default function Page() {
  return <AppShell roles={["hospital"]}>{() => <Dashboard />}</AppShell>;
}
