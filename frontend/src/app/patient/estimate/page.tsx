"use client";

import { FormEvent, useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { ShapBars } from "@/components/charts";
import { Alert, Loading, PageHead, Panel, useApi } from "@/components/ui";
import { api, CostEstimate, Profile } from "@/lib/api";
import { FEATURE_LABELS, inr, usd } from "@/lib/format";

function Estimate() {
  const { data: profile, error } = useApi<Profile>("/api/patients/me/profile");
  const [form, setForm] = useState<Profile | null>(null);
  const { data: history } = useApi<CostEstimate[]>("/api/cost/estimates");
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "error" | "ok"; text: string } | null>(null);

  useEffect(() => {
    if (profile) setForm(profile);
  }, [profile]);

  useEffect(() => {
    if (history?.length) setEstimate((current) => current ?? history[0]);
  }, [history]);

  if (!form) return <Loading error={error} />;

  const set = (k: keyof Profile, num = false) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: num ? Number(e.target.value) : e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      await api("/api/patients/me/profile", { method: "PUT", body: form });
      setEstimate(await api<CostEstimate>("/api/cost/estimate", { body: {} }));
      setMsg({ kind: "ok", text: "Profile saved and estimate updated." });
    } catch (err) {
      setMsg({ kind: "error", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  const shapTotal = estimate ? estimate.shap.reduce((s, x) => s + x.shap_usd, 0) : 0;

  return (
    <>
      <PageHead title="Treatment cost estimate"
        sub="The cost prediction model (Gradient Boosting, chosen over Linear Regression, Random Forest and XGBoost by lowest RMSE) estimates yearly medical expenses from your profile." />
      <div className="cols-2">
        <Panel title="Your profile" hint="Health details feed the cost model; finance details feed bill payment advice.">
          <form className="form" onSubmit={submit}>
            <div className="form-row">
              <label className="field">Age<input id="age" type="number" min={18} max={100} required value={form.age} onChange={set("age", true)} /></label>
              <label className="field">Sex
                <select id="sex" value={form.sex} onChange={set("sex")}><option value="male">Male</option><option value="female">Female</option></select>
              </label>
              <label className="field">BMI<input id="bmi" type="number" step="0.1" min={10} max={70} required value={form.bmi} onChange={set("bmi", true)} /></label>
            </div>
            <div className="form-row">
              <label className="field">Children<input id="children" type="number" min={0} max={10} required value={form.children} onChange={set("children", true)} /></label>
              <label className="field">Smoker
                <select id="smoker" value={form.smoker} onChange={set("smoker")}><option value="no">No</option><option value="yes">Yes</option></select>
              </label>
              <label className="field">Region
                <select id="region" value={form.region} onChange={set("region")}>
                  {["northeast", "northwest", "southeast", "southwest"].map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </label>
            </div>
            <div className="form-row">
              <label className="field">Marital status
                <select id="marital" value={form.marital_status} onChange={set("marital_status")}>
                  {["Single", "Married", "Divorced", "Widowed"].map((r) => <option key={r}>{r}</option>)}
                </select>
              </label>
              <label className="field">Employment
                <select id="employment" value={form.employment_status} onChange={set("employment_status")}>
                  {["Employed", "Unemployed", "Retired", "Student"].map((r) => <option key={r}>{r}</option>)}
                </select>
              </label>
            </div>
            <div className="form-row">
              <label className="field">Monthly income (₹)<input id="income" type="number" min={0} value={form.monthly_income} onChange={set("monthly_income", true)} /></label>
              <label className="field">Existing EMIs per month (₹)<input id="debt" type="number" min={0} value={form.existing_monthly_debt} onChange={set("existing_monthly_debt", true)} /></label>
            </div>
            <label className="check">
              <input id="cc" type="checkbox" checked={form.has_credit_card} onChange={(e) => setForm({ ...form, has_credit_card: e.target.checked })} />
              I have a credit card
            </label>
            {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
            <div><button className="btn" disabled={busy}>{busy ? "Predicting…" : "Save and estimate"}</button></div>
          </form>
        </Panel>

        <Panel title="Estimate" hint="Model trained on the US Medical Cost dataset, so the figure is in US dollars; the rupee value is a direct conversion.">
          {estimate ? (
            <div className="stack">
              <div className="risk-dial">
                <span className="big">{usd(estimate.predicted_usd)}</span>
                <span className="muted">per year · ≈ {inr(estimate.predicted_inr)}</span>
              </div>
              <ShapBars
                items={estimate.shap.map((s) => ({ label: FEATURE_LABELS[s.feature] || s.feature, detail: String(s.value ?? ""), value: s.shap_usd }))}
                format={(n) => usd(n)} upLabel="Raises the estimate" downLabel="Lowers the estimate" />
              <p className="note-line">
                Base value (average patient) {usd(estimate.predicted_usd - shapTotal)} + contributions {usd(shapTotal)} = {usd(estimate.predicted_usd)}.
                SHAP values always add up to the prediction.
              </p>
            </div>
          ) : (
            <div className="muted">Save your profile to see the estimate and which factors drive it.</div>
          )}
        </Panel>
      </div>
    </>
  );
}

export default function Page() {
  return <AppShell roles={["patient"]}>{() => <Estimate />}</AppShell>;
}
