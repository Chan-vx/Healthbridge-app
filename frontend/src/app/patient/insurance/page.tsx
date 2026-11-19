"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { SplitBar } from "@/components/charts";
import PolicyTerms from "@/components/PolicyTerms";
import { ClaimStatusBadge, Empty, Kpi, Loading, PageHead, Panel, useApi } from "@/components/ui";
import { Coverage, Policy } from "@/lib/api";
import { date, inr } from "@/lib/format";

/** The same steps Member 3's cost calculator applies to every bill, on an example bill. */
function example(p: Policy, left: number) {
  const bill = 50000, room = 25000;
  const roomCap = p.room_rent_cap && room > p.room_rent_cap ? room - p.room_rent_cap : 0;
  const covered = bill - roomCap;
  const deductible = Math.min(p.deductible, covered);
  const coIns = (covered - deductible) * p.co_insurance_pct / 100;
  let insurer = covered - deductible - coIns;
  const overLimit = Math.max(insurer - left, 0);
  insurer -= overLimit;
  const copay = Math.min(p.copay_flat, insurer);
  insurer -= copay;
  const rows: [string, string, number][] = [
    ["Room rent cap", p.room_rent_cap ? `room charges above ${inr(p.room_rent_cap)}` : "no cap on your policy", roomCap],
    ["Deductible", "you pay this first", deductible],
    ["Co-insurance", `${p.co_insurance_pct}% of the rest`, coIns],
    ["Sum insured left", `the insurer pays at most ${inr(left)} more this year`, overLimit],
    ["Co-pay", "a fixed amount per bill", copay],
  ];
  return { bill, room, rows, insurer, patient: bill - insurer };
}

function MyInsurance() {
  const { data, error } = useApi<{ policy: Policy | null; coverage: Coverage | null }>("/api/policies/me");
  const [tab, setTab] = useState<"overview" | "terms">("overview");
  useEffect(() => {
    if (window.location.hash === "#terms") setTab("terms");  // linked from a bill's "Who pays what"
  }, []);
  if (!data) return <Loading error={error} />;
  const { policy: p, coverage: c } = data;
  if (!p || !c) {
    return (
      <>
        <PageHead title="My insurance" />
        <Panel title="No active policy"><Empty>Your insurer issues a policy from their HealthBridge workspace. Until then, you pay every bill in full.</Empty></Panel>
      </>
    );
  }
  const ex = example(p, c.left);
  const usedPct = c.sum_insured ? Math.round(((c.used + c.pending) / c.sum_insured) * 100) : 0;
  return (
    <>
      <PageHead title="My insurance" sub={`${p.insurer_name} · policy ${p.policy_number} · policy year ${date(c.year_start)} to ${date(c.year_end)}`}>
        <Link className="btn ghost" href="/patient/estimate">Estimate a treatment</Link>
      </PageHead>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "overview"} className={tab === "overview" ? "on" : ""} onClick={() => setTab("overview")}>Overview</button>
        <button role="tab" aria-selected={tab === "terms"} className={tab === "terms" ? "on" : ""} onClick={() => setTab("terms")}>Terms and conditions</button>
      </div>
      {tab === "terms" ? (
        <Panel title="Terms and conditions" hint={`${p.policy_number} · the rules every bill and claim on this policy follows`}>
          <PolicyTerms policy={p} coverage={c} />
        </Panel>
      ) : <>
      <div className="kpis">
        <Kpi label="Sum insured" value={inr(c.sum_insured)} sub="the most the insurer pays in a policy year" />
        <Kpi label="Paid or approved this year" value={inr(c.used)} />
        <Kpi label="Held by open claims" value={inr(c.pending)} sub="released if a claim is rejected or reduced" />
        <Kpi label="Left this year" value={inr(c.left)} tone={c.left <= 0 ? "bad" : usedPct >= 75 ? "warn" : "good"} sub={`renews ${date(c.year_end)}`} />
      </div>

      <div style={{ marginBottom: 16 }}>
        <Panel title="This year's sum insured" hint={`${usedPct}% used or held`}>
          <SplitBar parts={[
            { label: "Paid or approved", value: c.used, color: "var(--chart-2)", text: inr(c.used) },
            { label: "Held by open claims", value: c.pending, color: "var(--chart-4)", text: inr(c.pending) },
            { label: "Left", value: c.left, color: "var(--chart-1)", text: inr(c.left) },
          ]} />
        </Panel>
      </div>

      <div className="cols-2" style={{ marginBottom: 16 }}>
        <Panel title="Your plan">
          <dl className="kv">
            <dt>Sum insured (per policy year)</dt><dd>{inr(p.sum_insured)}</dd>
            <dt>Deductible (per bill)</dt><dd>{inr(p.deductible)}</dd>
            <dt>Co-insurance (your share)</dt><dd>{p.co_insurance_pct}%</dd>
            <dt>Co-pay (per bill)</dt><dd>{inr(p.copay_flat)}</dd>
            <dt>Room rent cap (per bill)</dt><dd>{p.room_rent_cap ? inr(p.room_rent_cap) : "No cap"}</dd>
            <dt>Policy started</dt><dd>{date(p.created_at)}</dd>
          </dl>
          <p className="note-line">Not covered: lines marked cosmetic, non-medical or non-empanelled.</p>
        </Panel>
        <Panel title="How a bill is split" hint={`Example: a ${inr(ex.bill)} bill with ${inr(ex.room)} of room rent, on your policy`} flush>
          <div className="table-wrap"><table>
            <thead><tr><th>Step</th><th>Rule</th><th className="num">You pay</th></tr></thead>
            <tbody>
              {ex.rows.map(([step, rule, amount]) => (
                <tr key={step}><td>{step}</td><td className="muted small">{rule}</td><td className="num">{inr(amount)}</td></tr>
              ))}
              <tr><td className="total"><b>Insurer pays</b></td><td /><td className="num"><b>{inr(ex.insurer)}</b></td></tr>
              <tr><td className="total"><b>You pay</b></td><td /><td className="num"><b>{inr(ex.patient)}</b></td></tr>
            </tbody>
          </table></div>
          <p className="note-line" style={{ padding: "0 16px 12px" }}>Every bill you upload is split with these steps (Member 3&apos;s cost calculator), using what is left of this year&apos;s sum insured.{" "}
            <button className="linklike" onClick={() => setTab("terms")}>Read the full terms</button></p>
        </Panel>
      </div>

      <Panel title="Claims this policy year" flush actions={<Link className="btn ghost small" href="/claims">All claims</Link>}>
        {c.claims.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Claim</th><th>Submitted</th><th>Status</th><th className="num">Claimed</th><th className="num">Uses of sum insured</th></tr></thead>
            <tbody>{c.claims.map((x) => (
              <tr key={x.id}>
                <td className="mono"><Link href={`/claims/${x.id}`}>{x.claim_number}</Link></td>
                <td>{date(x.submitted_at)}</td><td><ClaimStatusBadge status={x.status} /></td>
                <td className="num">{inr(x.claim_amount)}</td>
                <td className="num">{!x.counts ? "—" : x.status === "submitted" ? `${inr(x.claim_amount)} held` : inr(x.approved_amount)}</td>
              </tr>))}
            </tbody>
          </table></div>
        ) : <Empty>No claims yet this policy year.</Empty>}
      </Panel>
      </>}
    </>
  );
}

export default function Page() {
  return <AppShell roles={["patient"]}>{() => <MyInsurance />}</AppShell>;
}
