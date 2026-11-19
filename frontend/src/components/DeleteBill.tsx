"use client";

import { useState } from "react";
import { api } from "@/lib/api";

/**
 * Patient only: delete a bill from their own account. The hospital (and insurer) keep it.
 * Asks in the page first. `asking` starts it already open (the bills list opens it from a row).
 */
export default function DeleteBill({ billId, onDeleted, onCancel, asking: startAsking = false, prompt }: {
  billId: number;
  onDeleted: () => void;
  onCancel?: () => void;
  asking?: boolean;
  prompt?: React.ReactNode;
}) {
  const [asking, setAsking] = useState(startAsking);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setErr(null);
    try {
      await api(`/api/bills/${billId}`, { method: "DELETE" });
      onDeleted();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function cancel() {
    setAsking(false);
    setErr(null);
    onCancel?.();
  }

  return (
    <span style={{ display: "inline-flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      {asking ? (
        <>
          <span className="small">{prompt ?? "Delete this bill from your account?"} The hospital keeps its copy.</span>
          {!err && <button className="btn danger small" disabled={busy} onClick={remove}>{busy ? "Deleting…" : "Yes, delete"}</button>}
          <button className="btn ghost small" disabled={busy} onClick={cancel}>{err ? "Close" : "Cancel"}</button>
        </>
      ) : (
        <button className="btn ghost small" onClick={() => setAsking(true)}
          title="Delete this bill from your account. The hospital keeps its copy.">Delete</button>
      )}
      {err && <span className="small" style={{ color: "var(--bad)", flexBasis: "100%" }}>{err}</span>}
    </span>
  );
}
