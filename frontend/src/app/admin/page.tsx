"use client";

import AppShell from "@/components/AppShell";
import { Kpi, Loading, PageHead, Panel, useApi } from "@/components/ui";
import { API_URL } from "@/lib/api";
import { date, titleCase } from "@/lib/format";

interface ModelStatus { loaded: boolean; name: string; error: string | null; threshold?: number | null; ocr_available?: boolean }
interface AdminDash {
  users_by_role: Record<string, number>;
  records: Record<string, number>;
  models: Record<string, ModelStatus>;
  users: { id: number; full_name: string; email: string; role: string; created_at: string }[];
}

const MODULE_OWNER: Record<string, string> = {
  cost: "Member 1 · cost_prediction_model.pkl",
  fraud: "Member 2 · robust_xgboost_fraud.pkl + isolation_forest.pkl",
  bill: "Member 3 · fair_price_model.pkl + lineitem_anomaly_model.pkl",
};

function Dashboard() {
  const { data, error } = useApi<AdminDash>("/api/dashboard/admin");
  if (!data) return <Loading error={error} />;
  return (
    <>
      <PageHead title="Administration" sub="Users, stored records and the health of the integrated models.">
        <a className="btn ghost" href={`${API_URL}/docs`} target="_blank" rel="noreferrer">API docs (Swagger)</a>
      </PageHead>
      <div className="kpis">
        {Object.entries(data.records).map(([k, v]) => <Kpi key={k} label={titleCase(k)} value={v} />)}
      </div>
      <div className="stack">
        <Panel title="Integrated models" flush>
          <div className="table-wrap"><table>
            <thead><tr><th>Module</th><th>Model</th><th>Source</th><th>Status</th><th>Notes</th></tr></thead>
            <tbody>{Object.entries(data.models).map(([k, m]) => (
              <tr key={k}>
                <td>{titleCase(k)}</td><td>{m.name}</td><td className="muted">{MODULE_OWNER[k]}</td>
                <td>{m.loaded ? <span className="badge b-good">Loaded</span> : <span className="badge b-bad">Failed</span>}</td>
                <td className="small muted">
                  {m.error || (k === "fraud" ? `Decision threshold ${m.threshold}` : k === "bill" ? (m.ocr_available ? "Tesseract OCR available" : "Tesseract not installed: image upload disabled, sample and manual entry work") : "")}
                </td>
              </tr>))}
            </tbody>
          </table></div>
        </Panel>
        <Panel title="Users" flush hint={Object.entries(data.users_by_role).map(([r, n]) => `${n} ${r}`).join(" · ")}>
          <div className="table-wrap"><table>
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Joined</th></tr></thead>
            <tbody>{data.users.map((u) => (
              <tr key={u.id}><td>{u.full_name}</td><td>{u.email}</td><td>{titleCase(u.role)}</td><td>{date(u.created_at)}</td></tr>))}
            </tbody>
          </table></div>
        </Panel>
      </div>
    </>
  );
}

export default function Page() {
  return <AppShell roles={["admin"]}>{() => <Dashboard />}</AppShell>;
}
