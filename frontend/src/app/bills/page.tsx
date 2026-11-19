"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import AppShell from "@/components/AppShell";
import DeleteBill from "@/components/DeleteBill";
import { Alert, CheckBadge, ClaimStatusBadge, Empty, Loading, PageHead, Panel, PaymentBadge, useApi, VerificationBadge } from "@/components/ui";
import { api, BillDetail, BillSummary, Hospital, Person, User } from "@/lib/api";
import { date, inr } from "@/lib/format";

type Mode = "file" | "sample" | "manual";

/** Compare hospital names ignoring case and punctuation (OCR reads the printed name in capitals). */
const sameName = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

function NewBill({ user }: { user: User }) {
  const router = useRouter();
  const isHospital = user.role === "hospital";
  const { data: patients } = useApi<Person[]>(isHospital ? "/api/patients" : null);
  const { data: hospitals } = useApi<Hospital[]>(isHospital ? null : "/api/hospitals");
  const [mode, setMode] = useState<Mode>("file");
  const [party, setParty] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [rows, setRows] = useState([{ description: "", amount: "" }, { description: "", amount: "" }]);
  const [details, setDetails] = useState({ bill_number: "", admission_date: "", discharge_date: "" });
  const [recordOnly, setRecordOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const partyKey = isHospital ? "patient_id" : "hospital_id";

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (isHospital && !party) return setError("Choose the patient this bill belongs to.");
    setBusy(true);
    setError(null);
    try {
      let bill: BillDetail;
      if (mode === "manual") {
        const items = rows.filter((r) => r.description.trim() && Number(r.amount) > 0)
          .map((r) => ({ description: r.description.trim(), amount: Number(r.amount) }));
        if (!items.length) throw new Error("Add at least one line item with an amount.");
        const filled = Object.fromEntries(Object.entries(details).filter(([, v]) => v.trim()));
        bill = await api<BillDetail>("/api/bills/manual", {
          body: { [partyKey]: party ? Number(party) : null, items, ...filled, record_only: isHospital && recordOnly },
        });
      } else {
        const form = new FormData();
        if (party) form.append(partyKey, party);
        if (mode === "file") {
          if (!file) throw new Error("Choose a bill image or PDF.");
          form.append("file", file);
          if (isHospital && recordOnly) form.append("record_only", "true");
        }
        bill = await api<BillDetail>(mode === "file" ? "/api/bills/upload" : "/api/bills/sample", { form });
      }
      router.push(`/bills/${bill.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Panel title="Analyse a new bill"
      hint="OCR reads the bill, then duplicate detection, the fair-price model and the anomaly model check every line before insurance and EMI are worked out.">
      <div className="tabs" role="tablist">
        {([["file", "Upload image / PDF"], ["sample", "Use sample bill"], ["manual", "Enter items"]] as [Mode, string][]).map(([m, label]) => (
          <button key={m} type="button" role="tab" aria-selected={mode === m} className={mode === m ? "on" : undefined} onClick={() => setMode(m)}>{label}</button>
        ))}
      </div>
      <form className="form" onSubmit={submit}>
        {isHospital ? (
          <label className="field">Patient
            <select id="patient" required value={party} onChange={(e) => setParty(e.target.value)}>
              <option value="">Choose a patient…</option>
              {patients?.map((p) => <option key={p.id} value={p.id}>{p.full_name} · {p.email}</option>)}
            </select>
          </label>
        ) : (
          <label className="field">Hospital (sets the fair prices, and is asked to confirm the bill before you can claim it)
            <select id="hospital" value={party} onChange={(e) => setParty(e.target.value)}>
              <option value="">Not listed (tier 2, private)</option>
              {hospitals?.map((h) => <option key={h.id} value={h.id}>{h.name} · {h.city} ({h.city_tier}, {h.hospital_type})</option>)}
            </select>
          </label>
        )}
        {mode === "file" && (
          <label className="field">Bill image or PDF
            <input id="bill_file" type="file" accept=".png,.jpg,.jpeg,.tiff,.bmp,.pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </label>
        )}
        {mode === "sample" && (
          <p className="muted small" style={{ margin: 0 }}>
            Runs the full pipeline on the City Care sample bill from the bill &amp; finance module (₹1,26,320 with a duplicate paracetamol line and an overpriced CT scan).
          </p>
        )}
        {mode === "manual" && (
          <div className="stack" style={{ gap: 8 }}>
            <div className="form-row">
              <label className="field">Bill number<input id="m_bill_no" placeholder="e.g. CCH-2026-02500" value={details.bill_number}
                onChange={(e) => setDetails({ ...details, bill_number: e.target.value })} /></label>
              <label className="field">Admission date<input id="m_admission" type="date" value={details.admission_date}
                onChange={(e) => setDetails({ ...details, admission_date: e.target.value })} /></label>
              <label className="field">Discharge date<input id="m_discharge" type="date" value={details.discharge_date}
                onChange={(e) => setDetails({ ...details, discharge_date: e.target.value })} /></label>
            </div>
            {rows.map((r, i) => (
              <div className="form-row" key={i} style={{ gridTemplateColumns: "1fr 140px" }}>
                <input id={`desc_${i}`} aria-label={`Item ${i + 1} description`} placeholder="e.g. Room Rent (3 days)" value={r.description}
                  onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))} />
                <input id={`amt_${i}`} aria-label={`Item ${i + 1} amount`} type="number" min={0} step="0.01" placeholder="Amount ₹" value={r.amount}
                  onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))} />
              </div>
            ))}
            <div><button type="button" className="btn ghost small" onClick={() => setRows([...rows, { description: "", amount: "" }])}>Add line</button></div>
          </div>
        )}
        {isHospital && mode !== "sample" && (
          <label className="check">
            <input id="record_only" type="checkbox" checked={recordOnly} onChange={(e) => setRecordOnly(e.target.checked)} />
            Keep in hospital records only: the patient sees it when they upload a matching copy (or a claim is filed)
          </label>
        )}
        {error && <Alert>{error}</Alert>}
        <div><button className="btn" disabled={busy}>{busy ? "Analysing…" : "Analyse bill"}</button></div>
      </form>
    </Panel>
  );
}

function Bills({ user }: { user: User }) {
  const router = useRouter();
  const { data, error, setData } = useApi<BillSummary[]>("/api/bills");
  const isPatient = user.role === "patient";
  const [deleting, setDeleting] = useState<BillSummary | null>(null);
  const canUpload = user.role === "patient" || user.role === "hospital";
  return (
    <>
      <PageHead title={user.role === "patient" ? "My bills" : "Bills"}
        sub={user.role === "insurer" ? "Bills from your policyholders." : "Every bill is checked for duplicates and overcharges."} />
      <div className="stack">
        {canUpload && <NewBill user={user} />}
        <Panel title="All bills" flush>
          {deleting && data && (
            <div className="alert error" style={{ margin: "12px 16px" }}>
              <DeleteBill key={deleting.id} asking billId={deleting.id}
                prompt={<>Delete the <b>{deleting.hospital_name || "bill"}</b> bill of {date(deleting.created_at)} ({inr(deleting.total_billed)}) from your account?</>}
                onCancel={() => setDeleting(null)}
                onDeleted={() => { setData(data.filter((x) => x.id !== deleting.id)); setDeleting(null); }} />
            </div>
          )}
          {!data ? <div className="panel-body"><Loading error={error} /></div> : data.length === 0 ? <Empty>No bills yet.</Empty> : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>{user.role !== "patient" && <th>Patient</th>}<th>Hospital</th>
                    <th className="num">Billed</th><th className="num">Insurance</th><th className="num">Patient</th>
                    <th className="num">Flagged</th><th>Source</th><th>Checks</th><th>Claim</th><th>Payment</th>{isPatient && <th />}
                  </tr>
                </thead>
                <tbody>
                  {data.map((b) => (
                    <tr key={b.id} className="clickable" onClick={() => router.push(`/bills/${b.id}`)}>
                      <td>{date(b.created_at)}</td>
                      {user.role !== "patient" && <td>{b.patient_name}</td>}
                      <td>{b.registered_hospital || b.hospital_name || "—"}
                        {b.registered_hospital && b.hospital_name && sameName(b.hospital_name) !== sameName(b.registered_hospital) && (
                          <div className="small" style={{ color: "var(--bad)" }}>Bill says {b.hospital_name}</div>)}</td>
                      <td className="num">{inr(b.total_billed)}</td>
                      <td className="num">{inr(b.insurance_pays)}</td>
                      <td className="num">{inr(b.patient_out_of_pocket)}</td>
                      <td className="num" style={{ color: b.flagged_amount > 0 ? "var(--bad)" : undefined }}>{b.flagged_amount > 0 ? inr(b.flagged_amount) : "—"}</td>
                      <td><VerificationBadge status={b.verification_status} recordOnly={b.record_only} /></td>
                      <td><CheckBadge status={b.authenticity} /></td>
                      <td><ClaimStatusBadge status={b.claim_status} /></td>
                      <td><PaymentBadge status={b.payment_status} /></td>
                      {isPatient && <td><button className="btn ghost small" title="Delete this bill from your account. The hospital keeps its copy."
                        onClick={(e) => { e.stopPropagation(); setDeleting(b); }}>Delete</button></td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}

export default function Page() {
  return <AppShell roles={["patient", "hospital", "insurer", "finance", "admin"]}>{(user) => <Bills user={user} />}</AppShell>;
}
