"use client";

import { useCallback, useEffect, useState } from "react";
import { api, Claim } from "@/lib/api";
import { titleCase } from "@/lib/format";

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { data, error, loading, reload, setData };
}

export function PageHead({ title, sub, children }: { title: string; sub?: string; children?: React.ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {children && <div className="btn-row">{children}</div>}
    </div>
  );
}

export function Kpi({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: "good" | "warn" | "bad" }) {
  return (
    <div className={`kpi${tone ? ` tone-${tone}` : ""}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export function Panel({ title, hint, actions, flush, children }: {
  title: string; hint?: React.ReactNode; actions?: React.ReactNode; flush?: boolean; children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>{title}</h2>
          {hint && <div className="hint">{hint}</div>}
        </div>
        {actions}
      </div>
      <div className={`panel-body${flush ? " flush" : ""}`}>{children}</div>
    </section>
  );
}

export function Loading({ error }: { error?: string | null }) {
  if (error) return <div className="alert error">{error}</div>;
  return <div className="muted">Loading…</div>;
}

export function Alert({ kind = "error", children }: { kind?: "error" | "ok" | "info"; children: React.ReactNode }) {
  return <div className={`alert ${kind}`} role={kind === "error" ? "alert" : "status"}>{children}</div>;
}

export function RiskBadge({ level }: { level: Claim["risk_level"] }) {
  const cls = level === "HIGH" ? "b-bad" : level === "MEDIUM" ? "b-warn" : "b-good";
  return <span className={`badge ${cls}`}>{level}</span>;
}

export function ClaimStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="badge b-muted">Not claimed</span>;
  const cls = status === "approved" ? "b-info" : status === "settled" ? "b-good" : status === "rejected" ? "b-bad" : "b-warn";
  return <span className={`badge ${cls}`}>{titleCase(status)}</span>;
}

export function PaymentBadge({ status }: { status: string }) {
  const cls = status === "paid" ? "b-good" : status === "on_emi" ? "b-info" : "b-warn";
  const label = status === "on_emi" ? "On EMI" : titleCase(status);
  return <span className={`badge ${cls}`}>{label}</span>;
}

export function SeverityBadge({ severity }: { severity: string }) {
  if (severity === "high_risk") return <span className="badge b-bad">Overcharge</span>;
  if (severity === "review") return <span className="badge b-warn">Review</span>;
  return <span className="badge b-good">Fair</span>;
}

export function AdviceBadge({ decision, label }: { decision: string; label: string }) {
  const cls = decision === "approve" ? "b-good" : decision === "approve_reduced" ? "b-info"
    : decision === "verify" ? "b-warn" : "b-bad";
  return <span className={`badge ${cls}`}>{label}</span>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}
