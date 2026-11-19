"use client";

import { Fragment, useState } from "react";
import AppShell from "@/components/AppShell";
import { ImportanceBars, RocChart, TwoGroupScatter } from "@/components/charts";
import { Alert, Kpi, Loading, PageHead, Panel, useApi } from "@/components/ui";
import { date, inr, inrShort, pct, titleCase } from "@/lib/format";

/* ---------------------------------------------------------------- shapes of evaluation/evaluate_models.py */

interface Confusion { tn: number; fp: number; fn: number; tp: number }
interface Binary {
  precision: number; recall: number; f1: number; accuracy: number; false_positive_rate: number;
  confusion: Confusion; roc_auc?: number; pr_auc?: number; roc?: { fpr: number; tpr: number }[];
}
interface Perf {
  generated_at: string;
  treatment?: {
    checks: { name: string; passed: number; total: number; detail: string }[];
    grid: { treatment: string; code: string; package: number; rows: { hospital_type: string; tier3: number; tier2: number; metro: number }[] };
    range_pct: number;
  };
  cost: {
    dataset: { name: string; rows: number; train: number; test: number; split: string; features: string[] };
    metrics: { r2: number; train_r2: number; mae_inr: number; rmse_inr: number; mape_pct: number; within_20_pct: number };
    comparison: { model: string; r2: number; mae_inr: number; rmse_inr: number; selected: boolean }[];
    by_group: { group: string; n: number; r2: number; mae_inr: number }[];
    feature_importance: { feature: string; importance: number }[];
    scatter: { actual: number; predicted: number; smoker: boolean }[];
    usd_to_inr: number;
  };
  fraud: {
    dataset: { name: string; rows: number; fraud: number; fraud_pct: number; train: number; test: number; test_fraud: number; split: string; removed: string };
    threshold: number;
    xgboost: Binary; xgboost_at_050: Binary; isolation_forest: Binary;
    hybrid: Binary & { bands: { level: string; claims: number; fraud: number; fraud_rate: number }[] };
    threshold_sweep: { threshold: number; val_f1: number; test_fp: number; test_fn: number }[];
    cross_validation: { folds: { roc_auc: number; f1: number }[]; roc_auc_mean: number; f1_mean: number; f1_std: number };
    simple_rule: Binary & { claim_amount_min_usd: number; income_max_usd: number };
    feature_importance: { feature: string; importance: number }[];
    scatter: { amount_inr: number; income_inr: number; fraud: boolean }[];
  };
  bill: {
    fair_price: {
      dataset: { name: string; rows: number; train: number; test: number; split: string };
      metrics: { r2: number; mae_inr: number; mape_pct: number; noise_floor_pct: number };
      by_category: { category: string; n: number; mape_pct: number; mae_inr: number }[];
      importance: { feature: string; importance: number }[];
    };
    anomaly: {
      dataset: { name: string; rows: number; overcharged: number; note: string };
      isolation_forest: Binary; app_flagged: Binary; app_high_risk: Binary;
    };
  };
  ocr: {
    bills: number; lines_printed: number; amounts_correct: number; line_accuracy: number; avg_seconds: number; note: string;
    fields: Record<"bill_number" | "patient_name" | "hospital_name" | "total" | "dates", number>;
    rows: { file: string; lines_printed: number; lines_read: number; amounts_correct: number; bill_number: boolean; patient_name: boolean;
      hospital_name: boolean; total: boolean; dates: boolean; seconds: number }[];
  };
  authenticity: {
    fakes: number; fakes_caught: number; fakes_blocked: number; genuine: number; genuine_flagged: number; genuine_matched: number;
    confusion: Confusion; note: string;
    rows: { file: string; what: string; genuine: boolean; outcome: string; failed: string[]; warned: string[]; correct: boolean }[];
  };
}

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "cost", label: "Cost prediction · Member 1" },
  { key: "fraud", label: "Fraud detection · Member 2" },
  { key: "bill", label: "Bill analysis · Member 3" },
  { key: "auth", label: "Bill authenticity · Member 4" },
] as const;
type Tab = (typeof TABS)[number]["key"];

/* ---------------------------------------------------------------- small pieces */

const n = (x: number) => x.toLocaleString("en-IN");
const fileName = (f: string) => f.split("/").pop();

/** 2x2 confusion matrix: rows are the truth, columns the model's call. Correct cells tinted green, errors red. */
function ConfusionMatrix({ c, positive, negative, call = ["Flagged", "Not flagged"] }: {
  c: Confusion; positive: string; negative: string; call?: [string, string];
}) {
  const cell = (value: number, ok: boolean, what: string) => (
    <td className="num" style={{ background: value === 0 ? undefined : ok ? "var(--good-soft)" : "var(--bad-soft)", fontSize: 18, fontWeight: 700, padding: "12px 16px" }}>
      {n(value)}<div className="small muted" style={{ fontWeight: 400 }}>{what}</div>
    </td>
  );
  return (
    <div className="table-wrap">
      <table style={{ textAlign: "center" }}>
        <thead><tr><th style={{ textAlign: "left" }}>Actually ↓ · Model said →</th><th className="num">{call[0]}</th><th className="num">{call[1]}</th></tr></thead>
        <tbody>
          <tr><td style={{ textAlign: "left" }}><b>{positive}</b></td>{cell(c.tp, true, "caught")}{cell(c.fn, false, "missed")}</tr>
          <tr><td style={{ textAlign: "left" }}><b>{negative}</b></td>{cell(c.fp, false, "false alarm")}{cell(c.tn, true, "correctly passed")}</tr>
        </tbody>
      </table>
    </div>
  );
}

function Dataset({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <Fragment key={k}><dt>{k}</dt><dd style={{ textAlign: "left", fontFamily: "inherit" }}>{v}</dd></Fragment>
      ))}
    </dl>
  );
}

function Explain({ title = "What this means", children }: { title?: string; children: React.ReactNode }) {
  return (
    <div className="stack" style={{ gap: 8, fontSize: 13.5, lineHeight: 1.55 }}>
      <b>{title}</b>
      {children}
    </div>
  );
}

const Tick = ({ ok }: { ok: boolean }) => ok
  ? <span className="badge b-good">Read</span>
  : <span className="badge b-bad">Missed</span>;

/* ---------------------------------------------------------------- tabs */

function Overview({ d, go }: { d: Perf; go: (t: Tab) => void }) {
  const cards: { tab: Tab; who: string; title: string; metric: string; value: string; sub: string }[] = [
    { tab: "cost", who: "Member 1", title: "Cost prediction", metric: "R² on unseen patients", value: d.cost.metrics.r2.toFixed(3),
      sub: `${d.cost.dataset.test} test patients · Gradient Boosting` },
    { tab: "fraud", who: "Member 2", title: "Fraud detection", metric: "Frauds caught (recall)", value: pct(d.fraud.xgboost.recall, 0),
      sub: `${d.fraud.xgboost.confusion.tp} of ${d.fraud.dataset.test_fraud} frauds · ${d.fraud.xgboost.confusion.fp} false alarms in ${n(d.fraud.dataset.test)} claims` },
    { tab: "bill", who: "Member 3", title: "Fair price + OCR", metric: "Fair-price R²", value: d.bill.fair_price.metrics.r2.toFixed(3),
      sub: `OCR read ${d.ocr.amounts_correct} of ${d.ocr.lines_printed} bill lines correctly` },
    { tab: "auth", who: "Member 4", title: "Bill authenticity", metric: "Fake bills caught", value: `${d.authenticity.fakes_caught} / ${d.authenticity.fakes}`,
      sub: `${d.authenticity.genuine_flagged} of ${d.authenticity.genuine} genuine bills wrongly flagged` },
  ];
  return (
    <>
      <div className="kpis">
        {cards.map((c) => (
          <button key={c.tab} className="kpi" onClick={() => go(c.tab)} style={{ textAlign: "left", cursor: "pointer", font: "inherit", color: "inherit" }}>
            <div className="label">{c.who} · {c.title}</div>
            <div className="value">{c.value}</div>
            <div className="sub">{c.metric}<br />{c.sub}</div>
          </button>
        ))}
      </div>
      <div className="cols-2">
        <Panel title="How these numbers were measured">
          <Explain title="Every model is scored on data it never saw while training">
            <p style={{ margin: 0 }}>Each member split their data into a <b>training set</b> (to learn from) and a <b>test set</b> (kept aside).
              The evaluation script recreates exactly the same split (same file, same columns, same random seed), loads the
              model the app is running, and scores it only on the test rows.</p>
            <p style={{ margin: 0 }}>Where a member scored a model on its own training data, the script scores it on fresh data instead,
              and says so on that tab.</p>
            <p className="note-line" style={{ margin: 0 }}>Re-run: <code>docker compose run --rm -v ./backend:/srv -v ./test_samples:/srv/test_samples backend python evaluation/evaluate_models.py</code></p>
          </Explain>
        </Panel>
        <Panel title="Honest limits">
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13.5, lineHeight: 1.6 }}>
            <li><b>Public and synthetic data.</b> The cost and fraud models learnt from public US datasets (amounts converted at ₹{d.cost.usd_to_inr}/$);
              the fair-price model from generated Indian tariffs. They show the method works; real hospital and insurer data would be needed before use.</li>
            <li><b>The fraud dataset is easy.</b> Its fraud labels follow claim amount and income almost exactly, so near-perfect scores
              are expected. The fraud tab shows this.</li>
            <li><b>Authenticity was tested on our own fakes</b>, each made to test one check. It proves each check works, not how often a skilled forger is caught.</li>
          </ul>
        </Panel>
      </div>
    </>
  );
}

function CostTab({ c, t }: { c: Perf["cost"]; t?: Perf["treatment"] }) {
  const max = Math.ceil(Math.max(...c.scatter.flatMap((p) => [p.actual, p.predicted])) / 1e6) * 1e6;
  return (
    <>
      <div className="kpis">
        <Kpi label="R² (test set)" value={c.metrics.r2.toFixed(3)} tone="good" sub={`explains ${Math.round(c.metrics.r2 * 100)}% of the variation in cost`} />
        <Kpi label="Average error (MAE)" value={inr(c.metrics.mae_inr)} sub={`typical miss on a yearly bill · RMSE ${inr(c.metrics.rmse_inr)}`} />
        <Kpi label="Within ±20% of actual" value={`${c.metrics.within_20_pct}%`} sub="of test patients" />
        <Kpi label="Training R²" value={c.metrics.train_r2.toFixed(3)} sub="close to test R²: not overfitting" />
      </div>
      <div className="cols-2" style={{ marginBottom: 16 }}>
        <Panel title="Predicted vs actual yearly cost" hint={`${c.dataset.test} test patients. On the dashed line = perfect prediction.`}>
          <TwoGroupScatter xLabel="Actual cost" yLabel="Predicted cost" format={inrShort} diagonal={max}
            groups={[
              { name: "Non-smokers", color: "var(--chart-1)", points: c.scatter.filter((p) => !p.smoker).map((p) => ({ x: p.actual, y: p.predicted })) },
              { name: "Smokers", color: "var(--chart-2)", points: c.scatter.filter((p) => p.smoker).map((p) => ({ x: p.actual, y: p.predicted })) },
            ]} />
        </Panel>
        <Panel title="What drives the prediction" hint="Gradient Boosting feature importance (share of all splits' gain)">
          <ImportanceBars items={c.feature_importance.slice(0, 7).map((f) => ({ label: titleCase(f.feature), value: f.importance }))} />
          <p className="note-line">Smoking, BMI and age decide most of the cost, matching medical expectations. The app also shows SHAP values per patient.</p>
        </Panel>
      </div>
      <div className="cols-2">
        <Panel title="Why Gradient Boosting" hint="All four models trained on the same split, scored on the same test patients" flush>
          <div className="table-wrap"><table>
            <thead><tr><th>Model</th><th className="num">R²</th><th className="num">MAE</th><th className="num">RMSE</th></tr></thead>
            <tbody>{c.comparison.map((m) => (
              <tr key={m.model} style={m.selected ? { fontWeight: 700 } : undefined}>
                <td>{m.model}{m.selected && <span className="badge b-good" style={{ marginLeft: 8 }}>Used</span>}</td>
                <td className="num">{m.r2.toFixed(3)}</td><td className="num">{inr(m.mae_inr)}</td><td className="num">{inr(m.rmse_inr)}</td>
              </tr>))}
            </tbody>
          </table></div>
          <p className="note-line" style={{ padding: "0 16px 12px" }}>Chosen for the lowest RMSE: it makes the fewest large mistakes, which matter most when a patient plans money.</p>
        </Panel>
        <Panel title="Where it is weaker">
          <div className="table-wrap" style={{ marginBottom: 10 }}><table>
            <thead><tr><th>Patients</th><th className="num">Count</th><th className="num">R²</th><th className="num">MAE</th></tr></thead>
            <tbody>{c.by_group.map((g) => (
              <tr key={g.group}><td>{g.group}</td><td className="num">{g.n}</td><td className="num">{g.r2.toFixed(3)}</td><td className="num">{inr(g.mae_inr)}</td></tr>))}
            </tbody>
          </table></div>
          <Explain>
            <p style={{ margin: 0 }}>Among non-smokers, the model explains less of the variation. Some have very high costs the six inputs cannot explain
              (illness history is not in the data). Those are the blue points well below the dashed line: their real cost was far higher than predicted.</p>
            <Dataset rows={[["Dataset", c.dataset.name], ["Rows", `${n(c.dataset.rows)} (${c.dataset.train} train / ${c.dataset.test} test)`],
              ["Inputs", c.dataset.features.join(", ")], ["Split", c.dataset.split], ["Currency", `US dollars × ₹${c.usd_to_inr}`]]} />
          </Explain>
        </Panel>
      </div>
      {t && <TreatmentChecks t={t} />}
    </>
  );
}

const TYPE_LABEL: Record<string, string> = { government: "Government", private: "Private", multispeciality: "Multispeciality", premium: "Premium" };

/** The treatment cost estimate is a calculation, not a trained model: show what is checked instead of an accuracy score. */
function TreatmentChecks({ t }: { t: NonNullable<Perf["treatment"]> }) {
  const allPass = t.checks.every((c) => c.passed === c.total);
  return (
    <>
      <h3 style={{ margin: "24px 0 4px" }}>Treatment cost estimate</h3>
      <p className="muted" style={{ margin: "0 0 12px", fontSize: 13.5 }}>
        The model above estimates a person&apos;s <b>yearly</b> expenses; it never sees the treatment. The Cost estimate page also prices one
        treatment at one hospital. That estimate is a calculation, not a trained model, so it has no accuracy score: to measure one we would need
        real hospital bills for the same treatments. Here is what is checked instead.
      </p>
      <div className="cols-2" style={{ marginBottom: 16 }}>
        <Panel title="What each part rests on" flush>
          <div className="table-wrap"><table>
            <thead><tr><th>Part of the estimate</th><th>Backed by</th></tr></thead>
            <tbody>
              <tr><td>Package rate, implants, ward rate per day</td><td><span className="badge b-good">Official</span> AB PM-JAY HBP 2022 figures: nothing predicted</td></tr>
              <tr><td>Hospital type and city multipliers, room cost</td><td><span className="badge b-info">Tested</span> Member 3&apos;s fair-price model: the ±{t.range_pct}% range is its error on unseen data</td></tr>
              <tr><td>ICU, emergency, other illnesses, age 60+</td><td><span className="badge b-warn">Assumption</span> cannot be tested without hospital data; labelled on the page</td></tr>
            </tbody>
          </table></div>
        </Panel>
        <Panel title={allPass ? "Automated checks: all pass" : "Automated checks"} flush hint="Run over all 12 treatments, every hospital type and city">
          <div className="table-wrap"><table>
            <thead><tr><th>Check</th><th className="num">Passed</th></tr></thead>
            <tbody>{t.checks.map((c) => (
              <tr key={c.name}><td><b>{c.name}</b><div className="small muted">{c.detail}</div></td>
                <td className="num"><span className={`badge ${c.passed === c.total ? "b-good" : "b-bad"}`}>{c.passed} / {c.total}</span></td></tr>))}
            </tbody>
          </table></div>
        </Panel>
      </div>
      <div className="cols-2">
        <Panel title={`One treatment everywhere: ${t.grid.treatment}`} hint={`${t.grid.code} package ${inr(t.grid.package)} (private hospital, tier-3 city)`} flush>
          <div className="table-wrap"><table>
            <thead><tr><th>Hospital</th><th className="num">Tier-3 city</th><th className="num">Tier-2 city</th><th className="num">Metro</th></tr></thead>
            <tbody>{t.grid.rows.map((r) => (
              <tr key={r.hospital_type}><td>{TYPE_LABEL[r.hospital_type]}</td>
                <td className="num">{inr(r.tier3)}</td><td className="num">{inr(r.tier2)}</td><td className="num">{inr(r.metro)}</td></tr>))}
            </tbody>
          </table></div>
          <p className="note-line" style={{ padding: "0 16px 12px" }}>Standard stay, general ward, no extras. Prices rise left to right and top to bottom, as expected.</p>
        </Panel>
        <Panel title="What would make it measurable">
          <Explain title="Real bills, compared with the estimate">
            <p style={{ margin: 0 }}>Partner hospitals would share final bills for these treatments (anonymised). For each bill we would run the estimate
              with the same treatment, hospital, stay and illnesses, and report the average error and how often the real bill falls inside the range.
              The same bills would let us replace the amber assumptions with measured figures.</p>
            <p style={{ margin: 0 }}>Package rates are what the government scheme pays; private hospitals often charge more, so we expect real private
              bills to land in the upper part of the range or above it.</p>
          </Explain>
        </Panel>
      </div>
    </>
  );
}

function FraudTab({ f }: { f: Perf["fraud"] }) {
  const x = f.xgboost;
  const amountMin = f.simple_rule.claim_amount_min_usd * 83;
  const incomeMax = f.simple_rule.income_max_usd * 83;
  const maxAmount = Math.max(...f.scatter.map((p) => p.amount_inr));
  const minIncome = Math.min(...f.scatter.map((p) => p.income_inr));
  return (
    <>
      <div className="kpis">
        <Kpi label="Frauds caught (recall)" value={pct(x.recall, 0)} tone="good" sub={`${x.confusion.tp} of ${x.confusion.tp + x.confusion.fn} test frauds`} />
        <Kpi label="Precision" value={pct(x.precision, 1)} sub={`${x.confusion.fp} false alarms among ${x.confusion.tp + x.confusion.fp} flagged`} />
        <Kpi label="F1 score" value={x.f1.toFixed(3)} sub={`threshold ${f.threshold}`} />
        <Kpi label="ROC-AUC" value={(x.roc_auc ?? 0).toFixed(3)} sub={`PR-AUC ${(x.pr_auc ?? 0).toFixed(3)}`} />
        <Kpi label="5-fold cross-validation" value={`F1 ${f.cross_validation.f1_mean.toFixed(3)}`} sub={`± ${f.cross_validation.f1_std.toFixed(3)} across folds · not a lucky split`} />
      </div>
      <div className="cols-2" style={{ marginBottom: 16 }}>
        <Panel title="Confusion matrix · XGBoost" hint={`${n(f.dataset.test)} test claims the model never saw, threshold ${f.threshold}`}>
          <ConfusionMatrix c={x.confusion} positive="Fraud" negative="Legitimate" />
          <p className="note-line">Missing a fraud costs the insurer the whole claim; a false alarm costs a reviewer a few minutes. So the model is tuned to miss nothing.</p>
        </Panel>
        <Panel title="ROC curve" hint="Frauds caught at each rate of false alarms; top-left is best. XGBoost and the hybrid overlap along the top edge.">
          <RocChart series={[
            { name: "XGBoost", color: "var(--chart-1)", auc: x.roc_auc ?? 0, points: x.roc ?? [] },
            { name: "Hybrid (0.8 XGBoost + 0.2 IF)", color: "var(--chart-3)", auc: f.hybrid.roc_auc ?? 0, points: f.hybrid.roc ?? [] },
            { name: "Isolation Forest alone", color: "var(--chart-2)", auc: f.isolation_forest.roc_auc ?? 0, points: f.isolation_forest.roc ?? [] },
          ]} />
        </Panel>
      </div>
      <div className="cols-2" style={{ marginBottom: 16 }}>
        <Panel title="Why the threshold is 0.05" flush>
          <div className="table-wrap"><table>
            <thead><tr><th className="num">Threshold</th><th className="num">Validation F1</th><th className="num">Test: false alarms</th><th className="num">Test: frauds missed</th></tr></thead>
            <tbody>{f.threshold_sweep.filter((t) => [0.05, 0.1, 0.3, 0.35, 0.5, 0.7, 0.9].includes(t.threshold)).map((t) => (
              <tr key={t.threshold} style={t.threshold === f.threshold ? { fontWeight: 700, background: "var(--accent-soft)" } : undefined}>
                <td className="num">{t.threshold.toFixed(2)}</td><td className="num">{t.val_f1.toFixed(3)}</td>
                <td className="num">{t.test_fp}</td><td className="num">{t.test_fn}</td>
              </tr>))}
            </tbody>
          </table></div>
          <div style={{ padding: "12px 16px" }}>
            <Explain>
              <p style={{ margin: 0 }}>Member 2 held back 20% of the training claims as a <b>validation set</b> and tried thresholds from 0.05 to 0.50.
                Every one scored a perfect F1 there, so the lowest was kept: it leaves the most room to catch frauds that look
                less obvious.</p>
              <p style={{ margin: 0 }}>The test set confirms the choice: at 0.05 no fraud is missed (2 false alarms); from 0.35 up, one fraud slips through.</p>
            </Explain>
          </div>
        </Panel>
        <Panel title="Hybrid risk levels on the test claims" flush>
          <div className="table-wrap"><table>
            <thead><tr><th>Risk level</th><th>Hybrid score</th><th className="num">Claims</th><th className="num">Actually fraud</th></tr></thead>
            <tbody>{f.hybrid.bands.map((b) => (
              <tr key={b.level}><td>{b.level}</td><td>{b.level === "LOW" ? "< 0.40" : b.level === "MEDIUM" ? "0.40 – 0.70" : "≥ 0.70"}</td>
                <td className="num">{b.claims}</td><td className="num">{b.fraud} ({pct(b.fraud_rate, 0)})</td></tr>))}
            </tbody>
          </table></div>
          <div style={{ padding: "12px 16px" }}>
            <Explain title="Why Isolation Forest is in the hybrid">
              <p style={{ margin: 0 }}>Alone it is weak (AUC {(f.isolation_forest.roc_auc ?? 0).toFixed(2)}): it never sees fraud labels, only learns what normal claims look like.
                It gets 20% of the score so that a <b>new kind of fraud</b> the XGBoost model was never shown can still raise the risk.</p>
            </Explain>
          </div>
        </Panel>
      </div>
      <div className="cols-2">
        <Panel title="Why the scores are so high" hint={`Test claims: all ${f.scatter.filter((p) => p.fraud).length} frauds and a sample of 300 legitimate ones`}>
          <TwoGroupScatter xLabel="Claim amount" yLabel="Patient yearly income" format={inrShort}
            region={{ x1: amountMin, x2: maxAmount, y1: minIncome, y2: incomeMax, label: "High claim + low income" }}
            groups={[
              { name: "Legitimate", color: "var(--chart-1)", points: f.scatter.filter((p) => !p.fraud).map((p) => ({ x: p.amount_inr, y: p.income_inr })) },
              { name: "Fraud", color: "var(--chart-2)", points: f.scatter.filter((p) => p.fraud).map((p) => ({ x: p.amount_inr, y: p.income_inr })) },
            ]} />
        </Panel>
        <Panel title="Read this before the numbers">
          <Explain title="The dataset's fraud labels follow a simple pattern">
            <p style={{ margin: 0 }}>Every fraud in this dataset has a claim of at least {inr(amountMin)} <b>and</b> an income below {inr(incomeMax)}.
              A two-line rule using just those cut-offs scores F1 {f.simple_rule.f1.toFixed(2)} on the same test claims. The model has learnt that pattern
              (claim amount and income are its two most important inputs), so its near-perfect scores reflect the dataset, not real-world accuracy.</p>
            <p style={{ margin: 0 }}>What this shows is that the pipeline is <b>sound</b>: answer-leaking columns removed ({f.dataset.removed}), a stratified split,
              threshold chosen on validation data, a cross-validated result and explanations for every claim. On real insurer data the
              same pipeline would score lower and need retraining.</p>
            <Dataset rows={[["Dataset", f.dataset.name], ["Claims", `${n(f.dataset.rows)} (${f.dataset.fraud} fraud, ${f.dataset.fraud_pct}%)`],
              ["Split", f.dataset.split]]} />
          </Explain>
        </Panel>
      </div>
    </>
  );
}

function BillTab({ b, o }: { b: Perf["bill"]; o: Perf["ocr"] }) {
  const fp = b.fair_price;
  const an = b.anomaly;
  const fieldLabels: [keyof Perf["ocr"]["fields"], string][] = [["bill_number", "Bill number"], ["patient_name", "Patient name"],
    ["hospital_name", "Hospital name"], ["dates", "Admission / discharge"], ["total", "Printed total"]];
  return (
    <>
      <div className="kpis">
        <Kpi label="Fair price R²" value={fp.metrics.r2.toFixed(3)} tone="good" sub={`${fp.dataset.test} test line items`} />
        <Kpi label="Fair price error (MAPE)" value={`${fp.metrics.mape_pct}%`} sub={`the data's own noise is ${fp.metrics.noise_floor_pct}%: close to the best possible`} />
        <Kpi label="Overcharge detection AUC" value={(an.isolation_forest.roc_auc ?? 0).toFixed(3)} sub={`Isolation Forest on ${n(an.dataset.rows)} new line items`} />
        <Kpi label="OCR: bill lines read" value={pct(o.line_accuracy, 0)} tone="good" sub={`${o.amounts_correct} of ${o.lines_printed} amounts, ${o.bills} bills, ${o.avg_seconds}s each`} />
      </div>
      <div className="cols-2" style={{ marginBottom: 16 }}>
        <Panel title="Fair price model (Random Forest)" hint={fp.dataset.split} flush>
          <div className="table-wrap"><table>
            <thead><tr><th>Category</th><th className="num">Test items</th><th className="num">Avg. error</th><th className="num">MAPE</th></tr></thead>
            <tbody>{fp.by_category.map((c) => (
              <tr key={c.category}><td>{titleCase(c.category)}</td><td className="num">{c.n}</td><td className="num">{inr(c.mae_inr)}</td><td className="num">{c.mape_pct}%</td></tr>))}
            </tbody>
          </table></div>
          <div style={{ padding: "12px 16px" }}>
            <Explain>
              <p style={{ margin: 0 }}>The training prices were generated with ±18% random variation, so no model can be closer than about {fp.metrics.noise_floor_pct}% on average.
                At {fp.metrics.mape_pct}% the model has learnt the real pattern (category × city tier × hospital type × quantity) and little noise.
                The app pays charges up to fair price + 25%, comfortably above this error.</p>
            </Explain>
          </div>
        </Panel>
        <Panel title="Overcharge detection (Isolation Forest)" hint={an.dataset.name}>
          <ConfusionMatrix c={an.isolation_forest.confusion} positive="Overcharged" negative="Fairly priced" />
          <p className="note-line">Precision {pct(an.isolation_forest.precision, 0)} · recall {pct(an.isolation_forest.recall, 0)}. {an.dataset.note}</p>
          <Explain title="How the app uses it">
            <p style={{ margin: 0 }}>The app combines the model with the fair price. A line goes to <b>review</b> if the model flags it or it is 25% or more
              above its fair price, and is <b>high risk</b> only if the model flags it and it is 60% or more above. On this batch that sends
              {" "}{an.app_flagged.confusion.tp} of {an.dataset.overcharged} overcharges to review or high risk ({an.app_high_risk.confusion.tp} as high risk), and
              {" "}{an.app_flagged.confusion.fp} fairly priced lines to review: a person checks those before anything is cut.</p>
          </Explain>
        </Panel>
      </div>
      <Panel title="OCR on the sample bills" hint={o.note} flush>
        <div className="kpis" style={{ padding: "12px 16px 0", marginBottom: 8 }}>
          {fieldLabels.map(([k, label]) => <Kpi key={k} label={label} value={`${o.fields[k]} / ${o.bills}`} sub="read correctly" />)}
        </div>
        <div className="table-wrap"><table>
          <thead><tr><th>Bill</th><th className="num">Lines</th><th className="num">Amounts right</th><th>Bill no.</th><th>Patient</th><th>Hospital</th><th>Dates</th><th>Total</th></tr></thead>
          <tbody>{o.rows.map((r) => (
            <tr key={r.file}><td className="mono small">{fileName(r.file)}</td><td className="num">{r.lines_printed}</td>
              <td className="num">{r.amounts_correct} / {r.lines_printed}</td>
              <td><Tick ok={r.bill_number} /></td><td><Tick ok={r.patient_name} /></td><td><Tick ok={r.hospital_name} /></td>
              <td><Tick ok={r.dates} /></td><td><Tick ok={r.total} /></td></tr>))}
          </tbody>
        </table></div>
      </Panel>
    </>
  );
}

const OUTCOME: Record<string, [string, string]> = {
  matched: ["b-good", "Matches hospital record"],
  awaiting: ["b-info", "Waits for hospital"],
  warning: ["b-warn", "Warning"],
  blocked: ["b-bad", "Blocked"],
  refused: ["b-bad", "Refused at upload"],
  error: ["b-bad", "Error"],
};

/** Check names say what passing means; for a failed check, say what went wrong. */
const reason = (check: string) => check === "Matches the hospital's record" ? "Differs from the hospital's record" : check;

function AuthTab({ a }: { a: Perf["authenticity"] }) {
  return (
    <>
      <div className="kpis">
        <Kpi label="Fake bills caught" value={`${a.fakes_caught} / ${a.fakes}`} tone="good" sub={`${a.fakes_blocked} blocked outright, ${a.fakes_caught - a.fakes_blocked} flagged for review`} />
        <Kpi label="Genuine bills wrongly flagged" value={`${a.genuine_flagged} / ${a.genuine}`} tone={a.genuine_flagged ? "bad" : "good"} sub="no honest patient blocked" />
        <Kpi label="Matched to hospital record" value={`${a.genuine_matched} / ${a.genuine}`} sub="the rest wait for the hospital to confirm" />
      </div>
      <div className="cols-2" style={{ marginBottom: 16 }}>
        <Panel title="Confusion matrix" hint="Every sample bill uploaded by a patient through the real app">
          <ConfusionMatrix c={a.confusion} positive="Fake" negative="Genuine" />
        </Panel>
        <Panel title="How it was tested">
          <Explain>
            <p style={{ margin: 0 }}>The script starts the real backend on an empty database, loads the demo data (patients, hospitals, the hospitals&apos; own records),
              logs in as each patient and uploads every file. The table shows what the app decided.</p>
            <p style={{ margin: 0 }}>Fakes are caught by <b>comparing with the hospital&apos;s own record</b> (changed amounts, re-used bill numbers),
              by <b>consistency checks</b> (wrong hospital, wrong patient, impossible dates) and by <b>file evidence</b> (editing software).
              Genuine bills either match the hospital&apos;s record or wait for the hospital to confirm them.</p>
            <p className="note-line" style={{ margin: 0 }}>{a.note}</p>
          </Explain>
        </Panel>
      </div>
      <Panel title="Every test bill" flush>
        <div className="table-wrap"><table>
          <thead><tr><th>File</th><th>What it is</th><th>Truth</th><th>App decided</th><th>Why</th><th>Correct?</th></tr></thead>
          <tbody>{a.rows.map((r, i) => {
            const [cls, label] = OUTCOME[r.outcome] ?? ["b-info", r.outcome];
            return (
              <tr key={i}>
                <td className="mono small">{fileName(r.file)}</td><td>{r.what}</td>
                <td>{r.genuine ? "Genuine" : <b>Fake</b>}</td>
                <td><span className={`badge ${cls}`}>{label}</span></td>
                <td className="small muted" style={{ maxWidth: 320 }}>{[...r.failed, ...r.warned].map(reason).join(" · ") || "—"}</td>
                <td>{r.correct ? <span className="badge b-good">Correct</span> : <span className="badge b-bad">Wrong</span>}</td>
              </tr>
            );
          })}</tbody>
        </table></div>
      </Panel>
    </>
  );
}

/* ---------------------------------------------------------------- page */

function Performance() {
  const { data, error } = useApi<Perf>("/api/models/performance");
  const [tab, setTab] = useState<Tab>("overview");
  if (!data) return <Loading error={error} />;
  const missing = (["cost", "fraud", "bill", "ocr", "authenticity"] as const).filter((k) => !data[k]);
  return (
    <>
      <PageHead title="Model performance" sub={`Every model scored on data it was not trained on · evaluated ${date(data.generated_at)}`} />
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} className={tab === t.key ? "on" : ""} onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </div>
      {missing.length > 0 && <Alert kind="info">Not evaluated yet: {missing.join(", ")}. Run evaluation/evaluate_models.py.</Alert>}
      {tab === "overview" && !missing.length && <Overview d={data} go={setTab} />}
      {tab === "cost" && data.cost && <CostTab c={data.cost} t={data.treatment} />}
      {tab === "fraud" && data.fraud && <FraudTab f={data.fraud} />}
      {tab === "bill" && data.bill && data.ocr && <BillTab b={data.bill} o={data.ocr} />}
      {tab === "auth" && data.authenticity && <AuthTab a={data.authenticity} />}
    </>
  );
}

export default function Page() {
  return <AppShell roles={["patient", "hospital", "insurer", "finance", "admin"]}>{() => <Performance />}</AppShell>;
}
