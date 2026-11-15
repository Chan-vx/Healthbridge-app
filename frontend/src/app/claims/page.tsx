"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import AppShell from "@/components/AppShell";
import { AdviceBadge, ClaimAction, ClaimStatusBadge, Empty, Loading, PageHead, Panel, RiskBadge, useApi } from "@/components/ui";
import { Claim, User } from "@/lib/api";
import { date, inr } from "@/lib/format";

const STATUSES = ["", "submitted", "approved", "rejected", "settled"];
// the insurer's queue holds only claims that still need action; decided ones are in Claims history
const OPEN_STATUSES = ["", "submitted", "approved"];
const RISKS = ["", "HIGH", "MEDIUM", "LOW"];

function Claims({ user }: { user: User }) {
  const router = useRouter();
  const insurer = user.role === "insurer";
  const [status, setStatus] = useState("");
  const [risk, setRisk] = useState("");
  const statusFilter = status || (insurer ? "submitted,approved" : "");
  const qs = new URLSearchParams({ ...(statusFilter && { status: statusFilter }), ...(risk && { risk }) }).toString();
  const { data, error } = useApi<Claim[]>(`/api/claims${qs ? `?${qs}` : ""}`);

  return (
    <>
      <PageHead title={insurer ? "Claims queue" : "Claims"}
        sub={insurer ? "Claims that need action, highest hybrid risk first. Decide to approve or reject; Settle once paid. Decided claims move to Claims history." : "Insurance claims and their review status."}>
        {insurer && <Link className="btn ghost" href="/insurance/history">Claims history</Link>}
      </PageHead>
      <Panel title={`${data?.length ?? "…"} claims`} flush actions={
        <div className="btn-row">
          <select id="f_status" aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: "auto" }}>
            {(insurer ? OPEN_STATUSES : STATUSES).map((s) => (
              <option key={s} value={s}>{s ? `Status: ${s}` : insurer ? "To decide or settle" : "All statuses"}</option>
            ))}
          </select>
          <select id="f_risk" aria-label="Filter by risk" value={risk} onChange={(e) => setRisk(e.target.value)} style={{ width: "auto" }}>
            {RISKS.map((s) => <option key={s} value={s}>{s ? `Risk: ${s}` : "All risk levels"}</option>)}
          </select>
        </div>
      }>
        {!data ? <div className="panel-body"><Loading error={error} /></div> : data.length === 0 ? <Empty>{insurer && !status && !risk ? "No claims need action right now. Decided claims are in Claims history." : "No claims match these filters."}</Empty> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Claim</th><th>Submitted</th><th>Patient</th><th>Hospital</th><th>Type</th><th className="num">Amount</th>
                  <th className="num">Fraud prob.</th><th className="num">Hybrid</th><th>Risk</th><th>Suggested</th><th>Status</th>{insurer && <th>Action</th>}</tr>
              </thead>
              <tbody>
                {data.map((c) => (
                  <tr key={c.id} className="clickable" onClick={() => router.push(`/claims/${c.id}`)}>
                    <td className="mono">{c.claim_number}</td>
                    <td>{date(c.submitted_at)}</td>
                    <td>{c.patient_name}</td>
                    <td>{c.hospital_name || "—"}</td>
                    <td>{c.claim_type}</td>
                    <td className="num">{inr(c.claim_amount)}</td>
                    <td className="num">{(c.fraud_probability * 100).toFixed(1)}%</td>
                    <td className="num">{c.hybrid_risk_score.toFixed(3)}</td>
                    <td><RiskBadge level={c.risk_level} /></td>
                    <td>{c.advice ? <AdviceBadge decision={c.advice.decision} label={c.advice.label} /> : "—"}</td>
                    <td><ClaimStatusBadge status={c.status} /></td>
                    {insurer && <td><ClaimAction claim={c} /></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}

export default function Page() {
  return <AppShell roles={["patient", "hospital", "insurer", "finance", "admin"]}>{(user) => <Claims user={user} />}</AppShell>;
}
