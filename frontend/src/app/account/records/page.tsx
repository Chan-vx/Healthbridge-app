"use client";

import { useState } from "react";
import AppShell from "@/components/AppShell";
import { Alert, Loading, PageHead, Panel, useApi } from "@/components/ui";
import { api, User } from "@/lib/api";

type Counts = Record<string, number>;
interface Result { action: "reset" | "delete"; removed: Counts; restored: (Counts & { skipped_claims: number }) | null }

const LABEL: Record<string, string> = { bills: "bills", claims: "claims", payments: "payments", cost_estimates: "cost estimates" };
const list = (c: Counts) => Object.entries(c).filter(([k]) => k in LABEL)
  .map(([k, v]) => `${v} ${v === 1 ? LABEL[k].replace(/s$/, "") : LABEL[k]}`).join(", ");

const SCOPE: Record<string, { what: string; kept: string; others: string }> = {
  patient: {
    what: "all your bills (including the ones hospitals issued to you), their claims and payments, and your cost estimates",
    kept: "Your login, your profile and your insurance policy.",
    others: "These bills and claims also disappear from the hospital's and the insurer's accounts.",
  },
  hospital: {
    what: "every bill at your hospital (your own and the copies patients uploaded), their claims and payments",
    kept: "Your login and your hospital's details.",
    others: "These bills and claims also disappear from the patients' and the insurer's accounts.",
  },
  insurer: {
    what: "every claim sent to you",
    kept: "Your login and the policies you issued. The bills stay with patients and hospitals, ready to be claimed again.",
    others: "These claims also disappear from the patients' and hospitals' accounts.",
  },
};

function Records({ user }: { user: User }) {
  const { data, error, setData } = useApi<{ role: string; counts: Counts }>("/api/account/records");
  const [confirm, setConfirm] = useState<"reset" | "delete" | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (!data) return <Loading error={error} />;
  const scope = SCOPE[user.role];

  async function run(action: "reset" | "delete") {
    setBusy(true);
    setErr(null);
    try {
      const r = await api<Result>("/api/account/records/clear", { body: { action } });
      setResult(r);
      setConfirm(null);
      setData(await api<{ role: string; counts: Counts }>("/api/account/records"));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const option = (action: "reset" | "delete", title: string, body: React.ReactNode, button: string, danger: boolean) => (
    <Panel title={title}>
      <div className="stack" style={{ gap: 12, fontSize: 13.5, lineHeight: 1.55 }}>
        {body}
        {confirm === action ? (
          <div className="stack" style={{ gap: 10 }}>
            <Alert kind="error">This removes {list(data.counts) || "nothing"} from your account{action === "reset" ? " and puts the demo data back" : ""}.
              It cannot be undone.</Alert>
            <div className="btn-row">
              <button className={`btn${danger ? " danger" : ""}`} disabled={busy} onClick={() => run(action)}>
                {busy ? (action === "reset" ? "Resetting… (up to 30 seconds the first time)" : "Deleting…") : `Yes, ${button.toLowerCase()}`}
              </button>
              <button className="btn ghost" disabled={busy} onClick={() => setConfirm(null)}>Cancel</button>
            </div>
          </div>
        ) : (
          <div><button className={`btn${danger ? " danger" : " ghost"}`} onClick={() => { setConfirm(action); setResult(null); }}>{button}</button></div>
        )}
      </div>
    </Panel>
  );

  return (
    <>
      <PageHead title="Clear my records" sub={`Your account now has ${list(data.counts) || "no records"}.`} />
      {result && (
        <div style={{ marginBottom: 16 }}>
          <Alert kind="ok">
            Removed {list(result.removed) || "nothing"}.
            {result.restored && <> Restored the demo data: {list(result.restored) || "nothing (this account is not part of the demo data)"}.</>}
            {result.restored?.skipped_claims ? ` ${result.restored.skipped_claims} demo claims were not restored because their bills are gone; reset the hospital or patient first.` : ""}
          </Alert>
        </div>
      )}
      {err && <div style={{ marginBottom: 16 }}><Alert>{err}</Alert></div>}
      <div className="cols-2" style={{ marginBottom: 16 }}>
        {option("reset", "Reset to demo data", <>
          <p style={{ margin: 0 }}>Your account goes back to how it was at the start: the demo examples come back, and anything added while testing is removed.</p>
          <p className="muted" style={{ margin: 0 }}>Use this before re-testing the same scenarios.</p>
        </>, "Reset to demo data", false)}
        {option("delete", "Delete everything", <>
          <p style={{ margin: 0 }}>Your account is emptied, to test from zero. The demo examples are removed too (you can get them back with a reset).</p>
        </>, "Delete everything", true)}
      </div>
      <Panel title="What is cleared">
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13.5, lineHeight: 1.7 }}>
          <li><b>Cleared:</b> {scope.what}.</li>
          <li><b>Kept:</b> {scope.kept}</li>
          <li><b>Other accounts:</b> {scope.others}</li>
        </ul>
      </Panel>
    </>
  );
}

export default function Page() {
  return <AppShell roles={["patient", "hospital", "insurer"]}>{(user) => <Records user={user} />}</AppShell>;
}
