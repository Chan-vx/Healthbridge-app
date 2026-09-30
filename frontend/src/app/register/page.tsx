"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { Alert } from "@/components/ui";
import { api, HOME, saveSession, User } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    full_name: "", email: "", password: "", role: "patient",
    organization_name: "", city: "", city_tier: "tier2", hospital_type: "private",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, string> = { ...form };
      if (form.role === "patient") {
        delete body.organization_name;
        delete body.city;
      }
      const res = await api<{ access_token: string; user: User }>("/api/auth/register", { body });
      saveSession(res.access_token, res.user);
      router.replace(res.user.role === "patient" ? "/patient/estimate" : HOME[res.user.role]);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  const org = form.role !== "patient";
  return (
    <div className="auth-wrap">
      <div className="auth-card stack">
        <section className="panel">
          <div className="panel-head"><h2>Create a HealthBridge account</h2></div>
          <div className="panel-body">
            <form className="form" onSubmit={submit}>
              <label className="field">I am a
                <select id="role" value={form.role} onChange={set("role")}>
                  <option value="patient">Patient</option>
                  <option value="hospital">Hospital</option>
                  <option value="insurer">Insurance company</option>
                </select>
              </label>
              <label className="field">Your name
                <input id="full_name" required minLength={2} value={form.full_name} onChange={set("full_name")} />
              </label>
              {org && (
                <label className="field">{form.role === "hospital" ? "Hospital name" : "Insurer name"}
                  <input id="organization_name" required value={form.organization_name} onChange={set("organization_name")} />
                </label>
              )}
              {form.role === "hospital" && (
                <div className="form-row">
                  <label className="field">City
                    <input id="city" value={form.city} onChange={set("city")} />
                  </label>
                  <label className="field">City tier
                    <select id="city_tier" value={form.city_tier} onChange={set("city_tier")}>
                      <option value="metro">Metro</option>
                      <option value="tier2">Tier 2</option>
                      <option value="tier3">Tier 3</option>
                    </select>
                  </label>
                  <label className="field">Hospital type
                    <select id="hospital_type" value={form.hospital_type} onChange={set("hospital_type")}>
                      <option value="government">Government</option>
                      <option value="private">Private</option>
                      <option value="multispeciality">Multispeciality</option>
                      <option value="premium">Premium</option>
                    </select>
                  </label>
                </div>
              )}
              <label className="field">Email
                <input id="reg_email" type="email" required value={form.email} onChange={set("email")} />
              </label>
              <label className="field">Password (at least 8 characters)
                <input id="reg_password" type="password" required minLength={8} value={form.password} onChange={set("password")} />
              </label>
              {error && <Alert>{error}</Alert>}
              <div className="btn-row">
                <button className="btn" type="submit" disabled={busy}>{busy ? "Creating…" : "Create account"}</button>
                <Link href="/login">I already have an account</Link>
              </div>
            </form>
          </div>
        </section>
      </div>
    </div>
  );
}
