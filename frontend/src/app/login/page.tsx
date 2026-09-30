"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { Alert } from "@/components/ui";
import { api, HOME, saveSession, User } from "@/lib/api";

const DEMO = [
  { email: "ramesh@patient.in", label: "Ramesh Kumar", role: "patient" },
  { email: "citycare@hospital.in", label: "City Care Hospital", role: "hospital" },
  { email: "claims@suraksha.in", label: "Suraksha Insurance", role: "insurer" },
  { email: "finance@healthbridge.in", label: "Finance team", role: "finance" },
  { email: "admin@healthbridge.in", label: "Platform admin", role: "admin" },
  { email: "priya@patient.in", label: "Priya Sharma", role: "patient" },
];
const DEMO_PASSWORD = "Demo@1234";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function login(e?: FormEvent, creds?: { email: string; password: string }) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ access_token: string; user: User }>("/api/auth/login", {
        body: creds || { email, password },
      });
      saveSession(res.access_token, res.user);
      router.replace(HOME[res.user.role]);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card stack">
        <div className="brand">
          <div className="brand-mark" aria-hidden>H</div>
          <div>
            <div className="brand-name">HealthBridge</div>
            <div className="brand-sub">Digital healthcare finance &amp; insurance</div>
          </div>
        </div>
        <section className="panel">
          <div className="panel-head"><h2>Log in</h2></div>
          <div className="panel-body">
            <form className="form" onSubmit={login}>
              <label className="field">Email
                <input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
              </label>
              <label className="field">Password
                <input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
              </label>
              {error && <Alert>{error}</Alert>}
              <div className="btn-row">
                <button className="btn" type="submit" disabled={busy}>{busy ? "Logging in…" : "Log in"}</button>
                <Link href="/register">Create an account</Link>
              </div>
            </form>
          </div>
        </section>
        <section className="panel">
          <div className="panel-head">
            <h2>Demo accounts</h2>
            <span className="hint">Password {DEMO_PASSWORD}</span>
          </div>
          <div className="panel-body">
            <div className="demo-grid">
              {DEMO.map((d) => (
                <button key={d.email} type="button" disabled={busy}
                  onClick={() => login(undefined, { email: d.email, password: DEMO_PASSWORD })}>
                  {d.label}<span className="r">{d.role}</span>
                </button>
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
