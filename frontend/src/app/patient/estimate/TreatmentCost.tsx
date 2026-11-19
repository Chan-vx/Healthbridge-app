"use client";

import { FormEvent, useState } from "react";
import { ShapBars } from "@/components/charts";
import { Alert, Kpi, Loading, Panel, useApi } from "@/components/ui";
import { api, Hospital } from "@/lib/api";
import { inr } from "@/lib/format";

interface Treatment { key: string; name: string; code: string; package_name: string; specialty: string; los: number;
  package: number; implant: number; implant_name: string | null; per_day: boolean }
interface Catalogue { treatments: Treatment[]; conditions: { key: string; label: string }[]; rooms: { key: string; label: string }[]; source: string }
interface Step { factor: string; amount: number; detail: string; source: string }
interface Result {
  treatment: { name: string; code: string; standard_days: number };
  steps: Step[]; total: number; low: number; high: number; range_pct: number;
  insurance: null | { policy_number: string; insurer: string; insurance_pays: number; patient_pays: number; deductible: number;
    co_insurance: number; copay: number; room_cap_deduction: number };
}

const TIERS = [["metro", "Metro city"], ["tier2", "Tier-2 city"], ["tier3", "Tier-3 city / town"]];
const TYPES = [["government", "Government"], ["private", "Private"], ["multispeciality", "Multispeciality"], ["premium", "Premium / corporate"]];
const SOURCE_BADGE: Record<string, string> = { "AB PM-JAY HBP 2022": "b-good", "Fair-price model (Member 3)": "b-info", Assumption: "b-warn" };

export default function TreatmentCost() {
  const { data: cat, error } = useApi<Catalogue>("/api/cost/treatments");
  const { data: hospitals } = useApi<Hospital[]>("/api/hospitals");
  const [form, setForm] = useState({ treatment: "appendix", city_tier: "metro", hospital_type: "multispeciality",
    ward_days: "", icu_days: "0", room: "general_ward", emergency: false, conditions: [] as string[] });
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!cat) return <Loading error={error} />;
  const t = cat.treatments.find((x) => x.key === form.treatment)!;
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const toggle = (c: string) => setForm({ ...form, conditions: form.conditions.includes(c) ? form.conditions.filter((x) => x !== c) : [...form.conditions, c] });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      setResult(await api<Result>("/api/cost/treatment", { body: {
        ...form, ward_days: form.ward_days === "" ? null : Number(form.ward_days), icu_days: Number(form.icu_days || 0) } }));
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const factors = result ? result.steps.filter((s) => s.factor !== "Package rate" && s.amount !== 0) : [];
  return (
    <div className="cols-2">
      <Panel title="Which treatment, where?" hint="Starts from the government package rate for the treatment, then adjusts for your hospital and stay.">
        <form className="form" onSubmit={submit}>
          <label className="field">Treatment
            <select id="treatment" value={form.treatment} onChange={(e) => setForm({ ...form, treatment: e.target.value, ward_days: "" })}>
              {cat.treatments.map((x) => <option key={x.key} value={x.key}>{x.name}</option>)}
            </select>
          </label>
          <p className="note-line" style={{ margin: 0 }}>
            Package {t.code}: {t.per_day ? `₹2,310 per day, typically ${t.los} days` : `${inr(t.package)} for ${t.los} day${t.los > 1 ? "s" : ""}`}
            {t.implant ? ` + ${t.implant_name} ${inr(t.implant)}` : ""} · {t.specialty}
          </p>
          {hospitals && hospitals.length > 0 && (
            <label className="field">Fill in from a hospital (optional)
              <select id="hospital" value="" onChange={(e) => {
                const h = hospitals.find((x) => String(x.id) === e.target.value);
                if (h) setForm({ ...form, city_tier: h.city_tier, hospital_type: h.hospital_type });
              }}>
                <option value="">Choose a hospital…</option>
                {hospitals.map((h) => <option key={h.id} value={h.id}>{h.name}, {h.city}</option>)}
              </select>
            </label>
          )}
          <div className="form-row">
            <label className="field">City<select id="city_tier" value={form.city_tier} onChange={set("city_tier")}>
              {TIERS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
            <label className="field">Hospital type<select id="hospital_type" value={form.hospital_type} onChange={set("hospital_type")}>
              {TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          </div>
          <div className="form-row">
            <label className="field">Days in ward<input id="ward_days" type="number" min={0} max={60} placeholder={`${t.los} (standard)`}
              value={form.ward_days} onChange={set("ward_days")} /></label>
            <label className="field">Days in ICU<input id="icu_days" type="number" min={0} max={30} value={form.icu_days} onChange={set("icu_days")} /></label>
            <label className="field">Room<select id="room" value={form.room} onChange={set("room")}>
              {cat.rooms.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}</select></label>
          </div>
          <label className="check"><input id="emergency" type="checkbox" checked={form.emergency}
            onChange={(e) => setForm({ ...form, emergency: e.target.checked })} />Emergency admission (not planned)</label>
          <div className="field" style={{ fontSize: 12.5 }}>Other illnesses
            <div className="btn-row" style={{ gap: 14, flexWrap: "wrap" }}>
              {cat.conditions.map((c) => (
                <label key={c.key} className="check"><input type="checkbox" checked={form.conditions.includes(c.key)} onChange={() => toggle(c.key)} />{c.label}</label>
              ))}
            </div>
          </div>
          {err && <Alert>{err}</Alert>}
          <div><button className="btn" disabled={busy}>{busy ? "Estimating…" : "Estimate the cost"}</button></div>
          <p className="note-line" style={{ margin: 0 }}>Your age comes from your profile (60+ adds a recovery day). {cat.source}</p>
        </form>
      </Panel>

      <Panel title="Estimated cost" hint={result ? `${result.treatment.name} · range ±${result.range_pct}% (the fair-price model's average error on unseen bills)` : undefined}>
        {!result ? <div className="muted">Choose a treatment and hospital, then press Estimate.</div> : (
          <div className="stack">
            <div className="risk-dial">
              <span className="big">{inr(result.total)}</span>
              <span className="muted">likely · {inr(result.low)} to {inr(result.high)}</span>
            </div>
            {result.insurance ? (
              <div className="kpis" style={{ marginBottom: 0 }}>
                <Kpi label={`${result.insurance.insurer} pays`} value={inr(result.insurance.insurance_pays)} tone="good" sub={`policy ${result.insurance.policy_number}`} />
                <Kpi label="You pay" value={inr(result.insurance.patient_pays)} tone={result.insurance.patient_pays > 0 ? "warn" : undefined}
                  sub={[result.insurance.deductible && `deductible ${inr(result.insurance.deductible)}`, result.insurance.co_insurance && `co-insurance ${inr(result.insurance.co_insurance)}`,
                    result.insurance.copay && `co-pay ${inr(result.insurance.copay)}`, result.insurance.room_cap_deduction && `room cap ${inr(result.insurance.room_cap_deduction)}`].filter(Boolean).join(" · ") || undefined} />
              </div>
            ) : <Alert kind="info">No active policy: you would pay the full amount.</Alert>}
            {factors.length > 0 && (
              <ShapBars items={factors.map((s) => ({ label: s.factor, value: s.amount }))} format={(n) => inr(n)}
                upLabel="Adds to the package rate" downLabel="Lowers it" />
            )}
            <div className="table-wrap"><table>
              <thead><tr><th>Step</th><th className="num">Amount</th><th>Based on</th></tr></thead>
              <tbody>
                {result.steps.map((s) => (
                  <tr key={s.factor}>
                    <td><b>{s.factor}</b><div className="small muted">{s.detail}</div></td>
                    <td className="num">{s.amount >= 0 && s.factor !== "Package rate" ? "+" : ""}{inr(s.amount)}</td>
                    <td><span className={`badge ${SOURCE_BADGE[s.source] || "b-muted"}`}>{s.source}</span></td>
                  </tr>
                ))}
                <tr><td className="total"><b>Estimated total</b></td><td className="num"><b>{inr(result.total)}</b></td><td /></tr>
              </tbody>
            </table></div>
            <p className="note-line" style={{ margin: 0 }}>
              Green: official package rates. Blue: learnt by Member 3&apos;s trained fair-price model. Amber: our assumptions, to be replaced
              with hospital data. Package rates are what the government scheme pays; private hospitals often charge more.
            </p>
          </div>
        )}
      </Panel>
    </div>
  );
}
