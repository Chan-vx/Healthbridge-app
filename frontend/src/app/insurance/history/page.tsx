"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import AppShell from "@/components/AppShell";
import { AdviceBadge, ClaimStatusBadge, Empty, Kpi, Loading, PageHead, Panel, RiskBadge, useApi } from "@/components/ui";
import { Claim } from "@/lib/api";
import { date, inr } from "@/lib/format";

const DECIDED = "approved,settled,rejected";

/** Did the insurer follow the Claim Decision Engine? Approving follows approve / reduced / verify;
 *  rejecting follows reject / hold for investigation. */
function followedAdvice(c: Claim): boolean | null {
  if (!c.advice) return null;
  const paid = c.status !== "rejected";
  return paid === ["approve", "approve_reduced", "verify"].includes(c.advice.decision);
}

function csv(rows: Claim[]): string {
  const head = ["Claim", "Patient", "Hospital", "Type", "Submitted", "Decided", "Claimed", "Approved", "Status", "Risk",
    "Suggested", "Note"];
  const cell = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  return [head, ...rows.map((c) => [c.claim_number, c.patient_name, c.hospital_name, c.claim_type, c.submitted_at.slice(0, 10),
    c.decided_at?.slice(0, 10), c.claim_amount, c.approved_amount ?? 0, c.status, c.risk_level, c.advice?.label, c.decision_note])]
    .map((r) => r.map(cell).join(",")).join("\n");
}

function History() {
  const router = useRouter();
  const { data, error } = useApi<Claim[]>(`/api/claims?status=${DECIDED}`);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (data || [])
      .filter((c) => !status || c.status === status)
      .filter((c) => !q || [c.claim_number, c.patient_name, c.hospital_name].some((v) => (v || "").toLowerCase().includes(q)))
      .sort((a, b) => (b.decided_at || b.submitted_at).localeCompare(a.decided_at || a.submitted_at));
  }, [data, status, search]);

  if (!data) return <Loading error={error} />;

  const claimed = rows.reduce((s, c) => s + c.claim_amount, 0);
  const approved = rows.filter((c) => c.status !== "rejected").reduce((s, c) => s + (c.approved_amount || 0), 0);
  const settled = rows.filter((c) => c.status === "settled").reduce((s, c) => s + (c.approved_amount || 0), 0);
  const rejected = rows.filter((c) => c.status === "rejected");
  const judged = rows.map(followedAdvice).filter((x) => x !== null);
  const agreed = judged.filter(Boolean).length;

  function download() {
    const url = URL.createObjectURL(new Blob([csv(rows)], { type: "text/csv" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "claims-history.csv" });
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <PageHead title="Claims history" sub="Every claim you have approved, settled or rejected, newest decision first.">
        <button className="btn ghost" onClick={download} disabled={!rows.length}>Download CSV</button>
      </PageHead>
      <div className="kpis">
        <Kpi label="Decided claims" value={rows.length} sub={`${inr(claimed)} claimed`} />
        <Kpi label="Approved" value={inr(approved)} tone="good" sub={`${rows.length - rejected.length} claims`} />
        <Kpi label="Paid to hospitals" value={inr(settled)} sub={`${inr(approved - settled)} approved, not yet settled`} />
        <Kpi label="Rejected" value={rejected.length} tone={rejected.length ? "bad" : undefined}
          sub={`${inr(rejected.reduce((s, c) => s + c.claim_amount, 0))} not paid`} />
        <Kpi label="Not paid of claimed" value={inr(claimed - approved)} sub="rejected + reduced approvals" />
        <Kpi label="Followed the recommendation" value={judged.length ? `${Math.round((agreed / judged.length) * 100)}%` : "—"}
          sub={`${agreed} of ${judged.length} decisions`} />
      </div>

      <Panel title={`${rows.length} decided claims`} flush actions={
        <div className="btn-row">
          <input id="h_search" aria-label="Search claims" placeholder="Search patient, claim or hospital" value={search}
            onChange={(e) => setSearch(e.target.value)} style={{ width: 260 }} />
          <select id="h_status" aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: "auto" }}>
            <option value="">All decisions</option>
            <option value="approved">Approved, not settled</option>
            <option value="settled">Settled</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>
      }>
        {rows.length === 0 ? <Empty>{data.length ? "No claims match these filters." : "No decided claims yet."}</Empty> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Claim</th><th>Patient</th><th>Hospital</th><th>Submitted</th><th>Decided</th><th className="num">Claimed</th>
                  <th className="num">Approved</th><th>Risk</th><th>Suggested</th><th>Decision</th><th>Note</th></tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id} className="clickable" onClick={() => router.push(`/claims/${c.id}`)}>
                    <td className="mono">{c.claim_number}</td>
                    <td>{c.patient_name}</td>
                    <td>{c.hospital_name || "—"}</td>
                    <td>{date(c.submitted_at)}</td>
                    <td>{date(c.decided_at)}</td>
                    <td className="num">{inr(c.claim_amount)}</td>
                    <td className="num">{c.status === "rejected" ? "—" : inr(c.approved_amount)}</td>
                    <td><RiskBadge level={c.risk_level} /></td>
                    <td>{c.advice ? <AdviceBadge decision={c.advice.decision} label={c.advice.label} /> : "—"}</td>
                    <td><ClaimStatusBadge status={c.status} /></td>
                    <td className="muted small" style={{ maxWidth: 260 }}>{c.decision_note || "—"}</td>
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
  return <AppShell roles={["insurer"]}>{() => <History />}</AppShell>;
}
