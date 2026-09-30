"use client";

import { FormEvent, useState } from "react";
import AppShell from "@/components/AppShell";
import { Alert, Empty, Loading, PageHead, Panel, useApi } from "@/components/ui";
import { api, Person, Policy } from "@/lib/api";
import { date, inr } from "@/lib/format";

function Policies() {
  const { data, error, reload } = useApi<Policy[]>("/api/policies");
  const { data: patients } = useApi<Person[]>("/api/patients");
  const [form, setForm] = useState({ patient_email: "", deductible: "5000", co_insurance_pct: "20", copay_flat: "500", room_rent_cap: "20000", sum_insured: "500000" });
  const [msg, setMsg] = useState<{ kind: "error" | "ok"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const p = await api<Policy>("/api/policies", {
        body: {
          patient_email: form.patient_email, deductible: Number(form.deductible), co_insurance_pct: Number(form.co_insurance_pct),
          copay_flat: Number(form.copay_flat), room_rent_cap: form.room_rent_cap ? Number(form.room_rent_cap) : null,
          sum_insured: form.sum_insured ? Number(form.sum_insured) : null,
        },
      });
      setMsg({ kind: "ok", text: `Issued ${p.policy_number} to ${p.patient_name}. Any earlier policy for this patient is now inactive.` });
      reload();
    } catch (err) {
      setMsg({ kind: "error", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHead title="Policies" sub="Policy terms drive the bill analyzer's insurance calculation." />
      <div className="stack">
        <Panel title="Issue a policy">
          <form className="form" onSubmit={submit}>
            <label className="field">Patient
              <select id="patient_email" required value={form.patient_email} onChange={set("patient_email")}>
                <option value="">Choose a patient…</option>
                {patients?.map((p) => <option key={p.id} value={p.email}>{p.full_name} · {p.email}</option>)}
              </select>
            </label>
            <div className="form-row">
              <label className="field">Sum insured (₹)<input id="sum_insured" type="number" min={0} value={form.sum_insured} onChange={set("sum_insured")} /></label>
              <label className="field">Deductible (₹)<input id="deductible" type="number" min={0} value={form.deductible} onChange={set("deductible")} /></label>
              <label className="field">Co-insurance (%)<input id="co_ins" type="number" min={0} max={100} value={form.co_insurance_pct} onChange={set("co_insurance_pct")} /></label>
              <label className="field">Copay per bill (₹)<input id="copay" type="number" min={0} value={form.copay_flat} onChange={set("copay_flat")} /></label>
              <label className="field">Room rent cap (₹, blank = none)<input id="room_cap" type="number" min={0} value={form.room_rent_cap} onChange={set("room_rent_cap")} /></label>
            </div>
            {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
            <div><button className="btn" disabled={busy}>{busy ? "Issuing…" : "Issue policy"}</button></div>
          </form>
        </Panel>
        <Panel title="Issued policies" flush>
          {!data ? <div className="panel-body"><Loading error={error} /></div> : data.length === 0 ? <Empty>No policies yet.</Empty> : (
            <div className="table-wrap"><table>
              <thead><tr><th>Policy</th><th>Patient</th><th className="num">Sum insured</th><th className="num">Deductible</th><th className="num">Co-ins.</th><th className="num">Copay</th><th className="num">Room cap</th><th>Issued</th><th>Status</th></tr></thead>
              <tbody>{data.map((p) => (
                <tr key={p.id}>
                  <td className="mono">{p.policy_number}</td><td>{p.patient_name}</td><td className="num">{inr(p.sum_insured)}</td>
                  <td className="num">{inr(p.deductible)}</td><td className="num">{p.co_insurance_pct}%</td><td className="num">{inr(p.copay_flat)}</td>
                  <td className="num">{p.room_rent_cap ? inr(p.room_rent_cap) : "—"}</td><td>{date(p.created_at)}</td>
                  <td>{p.active ? <span className="badge b-good">Active</span> : <span className="badge b-muted">Inactive</span>}</td>
                </tr>))}
              </tbody>
            </table></div>
          )}
        </Panel>
      </div>
    </>
  );
}

export default function Page() {
  return <AppShell roles={["insurer"]}>{() => <Policies />}</AppShell>;
}
