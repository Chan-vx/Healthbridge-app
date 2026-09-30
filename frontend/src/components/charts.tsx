"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useEffect, useRef, useState } from "react";
import { inrShort, monthLabel } from "@/lib/format";

/** Measures its own width and hands exact pixel sizes to the chart (more reliable than ResponsiveContainer). */
function Sized({ height, children }: { height: number; children: (width: number) => React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(Math.floor(el.getBoundingClientRect().width));
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return <div ref={ref} style={{ width: "100%", height }}>{width > 0 && children(width)}</div>;
}

const axis = { fontSize: 11, fill: "var(--muted)" };
const grid = { stroke: "var(--line)", strokeDasharray: "0", vertical: false };
const tooltipStyle = {
  contentStyle: { background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 6, fontSize: 12, color: "var(--ink)" },
  labelStyle: { color: "var(--ink)", fontWeight: 600 },
  itemStyle: { color: "var(--ink)" },
  cursor: { fill: "var(--surface-2)" },
};

/** Diverging SHAP bars: orange pushes the prediction up, blue pulls it down. */
export function ShapBars({ items, format, upLabel, downLabel }: {
  items: { label: string; value: number; detail?: string }[];
  format: (n: number) => string;
  upLabel: string;
  downLabel: string;
}) {
  const data = items.map((i) => ({ ...i, name: i.detail ? `${i.label} (${i.detail})` : i.label }));
  const height = 40 + data.length * 34;
  return (
    <div>
      <Sized height={height}>{(w) => (
          <BarChart width={w} height={height} data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }} barCategoryGap={8}>
            <CartesianGrid stroke="var(--line)" horizontal={false} />
            <XAxis type="number" tick={axis} tickFormatter={format} axisLine={false} tickLine={false} />
            <YAxis type="category" dataKey="name" tick={{ ...axis, fill: "var(--ink)" }} width={170} axisLine={false} tickLine={false} />
            <ReferenceLine x={0} stroke="var(--faint)" />
            <Tooltip {...tooltipStyle} formatter={(v) => [format(Number(v)), "SHAP contribution"]} />
            <Bar dataKey="value" maxBarSize={18} isAnimationActive={false}>
              {data.map((d) => (
                <Cell key={d.name} fill={d.value >= 0 ? "var(--chart-2)" : "var(--chart-1)"} />
              ))}
            </Bar>
          </BarChart>
      )}</Sized>
      <div className="legend">
        <span><i style={{ background: "var(--chart-2)" }} />{upLabel}</span>
        <span><i style={{ background: "var(--chart-1)" }} />{downLabel}</span>
      </div>
    </div>
  );
}

/** Monthly billed amount split into what insurance and patients pay. */
export function MonthlyShareChart({ rows }: { rows: { month: string; insurance: number; patient: number }[] }) {
  const data = rows.map((r) => ({ ...r, label: monthLabel(r.month) }));
  return (
    <Sized height={260}>{(w) => (
        <BarChart width={w} height={260} data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap="28%">
          <CartesianGrid {...grid} />
          <XAxis dataKey="label" tick={axis} axisLine={false} tickLine={false} />
          <YAxis tick={axis} tickFormatter={inrShort} axisLine={false} tickLine={false} width={56} />
          <Tooltip {...tooltipStyle} formatter={(v, n) => [inrShort(Number(v)), String(n)]} />
          <Legend wrapperStyle={{ fontSize: 12 }} iconType="square" iconSize={10} formatter={(v) => <span style={{ color: "var(--muted)" }}>{v}</span>} />
          <Bar dataKey="insurance" name="Insurance pays" stackId="a" fill="var(--chart-1)" stroke="var(--surface)" strokeWidth={1} maxBarSize={42} />
          <Bar dataKey="patient" name="Patient pays" stackId="a" fill="var(--chart-2)" stroke="var(--surface)" strokeWidth={1} radius={[4, 4, 0, 0]} maxBarSize={42} />
        </BarChart>
      )}</Sized>
  );
}

/** Claims per month by hybrid risk level (status colours, always with a legend). */
export function MonthlyRiskChart({ rows }: { rows: { month: string; HIGH: number; MEDIUM: number; LOW: number }[] }) {
  const data = rows.map((r) => ({ ...r, label: monthLabel(r.month) }));
  return (
    <Sized height={240}>{(w) => (
        <BarChart width={w} height={240} data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap="30%">
          <CartesianGrid {...grid} />
          <XAxis dataKey="label" tick={axis} axisLine={false} tickLine={false} />
          <YAxis tick={axis} allowDecimals={false} axisLine={false} tickLine={false} width={32} />
          <Tooltip {...tooltipStyle} />
          <Legend wrapperStyle={{ fontSize: 12 }} iconType="square" iconSize={10} formatter={(v) => <span style={{ color: "var(--muted)" }}>{v}</span>} />
          <Bar dataKey="LOW" name="Low risk" stackId="r" fill="var(--st-good)" stroke="var(--surface)" strokeWidth={1} maxBarSize={40} />
          <Bar dataKey="MEDIUM" name="Medium risk" stackId="r" fill="var(--st-warn)" stroke="var(--surface)" strokeWidth={1} maxBarSize={40} />
          <Bar dataKey="HIGH" name="High risk" stackId="r" fill="var(--st-bad)" stroke="var(--surface)" strokeWidth={1} radius={[4, 4, 0, 0]} maxBarSize={40} />
        </BarChart>
      )}</Sized>
  );
}

/** A single horizontal proportion bar with a labelled legend (not colour alone). */
export function SplitBar({ parts }: { parts: { label: string; value: number; color: string; text: string }[] }) {
  const total = parts.reduce((s, p) => s + p.value, 0) || 1;
  return (
    <div>
      <div className="split-bar" role="img" aria-label={parts.map((p) => `${p.label} ${p.text}`).join(", ")}>
        {parts.filter((p) => p.value > 0).map((p) => (
          <span key={p.label} title={`${p.label}: ${p.text}`} style={{ width: `${(p.value / total) * 100}%`, background: p.color, borderRight: "2px solid var(--surface)" }} />
        ))}
      </div>
      <div className="legend">
        {parts.map((p) => (
          <span key={p.label}><i style={{ background: p.color }} />{p.label} <b className="num" style={{ color: "var(--ink)" }}>{p.text}</b></span>
        ))}
      </div>
    </div>
  );
}
