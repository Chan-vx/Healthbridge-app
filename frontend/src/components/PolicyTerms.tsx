"use client";

import { Coverage, Policy } from "@/lib/api";
import { date, inr } from "@/lib/format";

/**
 * The plan's terms and conditions, with this policy's figures filled in. Each clause describes what the
 * platform actually does: backend/app/services/coverage.py (sum insured), Member 3's cost calculator
 * (the bill split), backend/app/routers/claims.py and services/claim_decision.py (claims).
 */
export default function PolicyTerms({ policy: p, coverage: c }: { policy: Policy; coverage?: Coverage | null }) {
  const anniversary = new Date(p.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "long" });
  const sections: { title: string; clauses: React.ReactNode[] }[] = [
    {
      title: "The policy",
      clauses: [
        <>Policy <b>{p.policy_number}</b> is issued by <b>{p.insurer_name}</b> to <b>{p.patient_name}</b>, starting on {date(p.created_at)}.</>,
        <>The <b>policy year</b> runs from {anniversary} each year to the day before the next {anniversary}
          {c ? <> (now {date(c.year_start)} to {date(c.year_end)})</> : null}.</>,
      ],
    },
    {
      title: "Sum insured",
      clauses: [
        <>The insurer pays at most <b>{inr(p.sum_insured)}</b> in total for all claims in one policy year.</>,
        <>An approved or settled claim uses the sum insured by its approved amount. A submitted claim holds its claimed amount until the
          insurer decides; a rejected claim, or the unapproved part of a reduced one, is released.</>,
        <>Bills are split, and claims filed and approved, only up to what is left of the year&apos;s sum insured. The rest is paid by the patient.</>,
        <>The sum insured renews in full at the start of each policy year. Any amount not used does not carry over.</>,
      ],
    },
    {
      title: "What is covered",
      clauses: [
        <>Charges on bills from hospitals on HealthBridge, once the hospital has submitted or confirmed the bill.</>,
        <><b>Not covered:</b> any line described as cosmetic, non-medical or from a non-empanelled provider.</>,
        <><b>Room rent cap:</b> {p.room_rent_cap ? <>room charges above <b>{inr(p.room_rent_cap)}</b> on a bill are not covered.</> : "this policy has no room rent cap."}</>,
      ],
    },
    {
      title: "What the patient pays on each bill",
      clauses: [
        <><b>Deductible:</b> the first <b>{inr(p.deductible)}</b> of the covered amount of each bill.</>,
        <><b>Co-insurance:</b> <b>{p.co_insurance_pct}%</b> of the covered amount after the deductible.</>,
        <><b>Co-pay:</b> a fixed <b>{inr(p.copay_flat)}</b> per bill, taken from the insurer&apos;s share.</>,
      ],
    },
    {
      title: "How each bill is split",
      clauses: [
        <>The steps are applied in this order: (1) remove lines that are not covered; (2) apply the room rent cap; (3) the deductible;
          (4) co-insurance; (5) limit the insurer&apos;s share to the sum insured left this year; (6) the co-pay.</>,
        <>The insurer pays what remains after these steps; the patient pays everything else. The two shares always add up to the bill.</>,
      ],
    },
    {
      title: "Claims",
      clauses: [
        <>A claim is filed by the patient or the hospital for a bill the hospital has submitted or confirmed. One bill can be claimed only once.</>,
        <>A bill cannot be claimed if the hospital disputed it, if a patient&apos;s copy differs from the hospital&apos;s own record, if it repeats an
          earlier bill, or if it comes from a hospital that is not on HealthBridge.</>,
        <>Every claim is scored for fraud risk and checked for authenticity, and the platform recommends a decision (for example, hold for
          investigation). The insurer then approves the claim, in full or for a reduced amount, or rejects it, and may add a note to the hospital.</>,
        <>A reduced amount may leave out duplicate charges and the part of any charge above its fair market price + 25%.</>,
        <>The approved amount can never exceed the claimed amount, or the sum insured left this year.</>,
      ],
    },
    {
      title: "The patient's share",
      clauses: [
        <>The patient may pay their share in full or in monthly instalments (EMI). The EMI amounts shown are estimates; the lender&apos;s terms apply.</>,
      ],
    },
  ];
  return (
    <div className="stack" style={{ gap: 18 }}>
      {sections.map((s, i) => (
        <section key={s.title}>
          <h3 style={{ margin: "0 0 6px", fontSize: 14.5 }}>{i + 1}. {s.title}</h3>
          <ol style={{ margin: 0, paddingLeft: 0, listStyle: "none", display: "grid", gap: 6, fontSize: 13.5, lineHeight: 1.55 }}>
            {s.clauses.map((clause, j) => (
              <li key={j} style={{ display: "grid", gridTemplateColumns: "34px 1fr" }}>
                <span className="muted mono small" style={{ paddingTop: 2 }}>{i + 1}.{j + 1}</span><span>{clause}</span>
              </li>
            ))}
          </ol>
        </section>
      ))}
      <p className="note-line" style={{ margin: 0 }}>
        These terms describe how HealthBridge calculates bills and claims in this project. They are not a legal insurance contract.
      </p>
    </div>
  );
}
