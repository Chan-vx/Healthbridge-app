"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  Scatter,
  ScatterChart,
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

/** ROC curves of one or more scores against the same test labels, with the chance diagonal. */
export function RocChart({ series }: { series: { name: string; color: string; auc: number; points: { fpr: number; tpr: number }[] }[] }) {
  const pctTick = (v: number) => `${Math.round(v * 100)}%`;
  return (
    <div>
      <Sized height={280}>{(w) => (
        <LineChart width={w} height={280} margin={{ top: 8, right: 16, bottom: 22, left: 4 }}>
          <CartesianGrid stroke="var(--line)" />
          <XAxis type="number" dataKey="fpr" domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tick={axis} tickFormatter={pctTick}
            axisLine={false} tickLine={false} label={{ value: "False alarms (false positive rate)", position: "insideBottom", offset: -12, fontSize: 11, fill: "var(--muted)" }} />
          <YAxis type="number" domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tick={axis} tickFormatter={pctTick} axisLine={false} tickLine={false} width={60}
            label={{ value: "Frauds caught", angle: -90, position: "insideLeft", offset: 0, fontSize: 11, fill: "var(--muted)" }} />
          <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="var(--faint)" strokeDasharray="4 4" />
          <Tooltip {...tooltipStyle} cursor={{ stroke: "var(--faint)" }} labelFormatter={(v) => `False alarms ${pctTick(Number(v))}`}
            formatter={(v, n) => [pctTick(Number(v)), `${n} · caught`]} />
          {series.map((s) => (
            <Line key={s.name} data={s.points} dataKey="tpr" name={s.name} type="linear" stroke={s.color} strokeWidth={2}
              dot={false} activeDot={{ r: 4, stroke: "var(--surface)", strokeWidth: 2 }} isAnimationActive={false} />
          ))}
        </LineChart>
      )}</Sized>
      <div className="legend">
        {series.map((s) => <span key={s.name}><i style={{ background: s.color }} />{s.name} <b className="num" style={{ color: "var(--ink)" }}>AUC {s.auc.toFixed(3)}</b></span>)}
        <span><i style={{ background: "var(--faint)" }} />Guessing (AUC 0.5)</span>
      </div>
    </div>
  );
}

type Pt = { x: number; y: number };

/** Two groups of points on shared axes; optional y = x line or a shaded rectangle to explain the result. */
export function TwoGroupScatter({ groups, xLabel, yLabel, format, diagonal, region }: {
  groups: { name: string; color: string; points: Pt[] }[];
  xLabel: string;
  yLabel: string;
  format: (n: number) => string;
  diagonal?: number;
  region?: { x1: number; x2: number; y1: number; y2: number; label: string };
}) {
  return (
    <div>
      <Sized height={300}>{(w) => (
        <ScatterChart width={w} height={300} margin={{ top: 8, right: 16, bottom: 22, left: 4 }}>
          <CartesianGrid stroke="var(--line)" />
          <XAxis type="number" dataKey="x" name={xLabel} tick={axis} tickFormatter={format} axisLine={false} tickLine={false}
            domain={diagonal ? [0, diagonal] : ["auto", "auto"]}
            label={{ value: xLabel, position: "insideBottom", offset: -12, fontSize: 11, fill: "var(--muted)" }} />
          <YAxis type="number" dataKey="y" name={yLabel} tick={axis} tickFormatter={format} axisLine={false} tickLine={false} width={58}
            domain={diagonal ? [0, diagonal] : ["auto", "auto"]}
            label={{ value: yLabel, angle: -90, position: "insideLeft", offset: 4, fontSize: 11, fill: "var(--muted)" }} />
          {region && <ReferenceArea x1={region.x1} x2={region.x2} y1={region.y1} y2={region.y2} fill="var(--chart-2)" fillOpacity={0.08}
            stroke="var(--chart-2)" strokeDasharray="4 4" label={{ value: region.label, position: "top", fontSize: 11, fill: "var(--ink)" }} />}
          {diagonal && <ReferenceLine segment={[{ x: 0, y: 0 }, { x: diagonal, y: diagonal }]} stroke="var(--faint)" strokeDasharray="4 4" />}
          <Tooltip {...tooltipStyle} cursor={{ strokeDasharray: "3 3", stroke: "var(--faint)" }} formatter={(v, n) => [format(Number(v)), String(n)]} />
          {groups.map((g) => (
            <Scatter key={g.name} name={g.name} data={g.points} fill={g.color} fillOpacity={0.75} stroke="var(--surface)" strokeWidth={1}
              shape="circle" isAnimationActive={false} />
          ))}
        </ScatterChart>
      )}</Sized>
      <div className="legend">
        {groups.map((g) => <span key={g.name}><i style={{ background: g.color }} />{g.name} <span className="muted">({g.points.length})</span></span>)}
        {diagonal && <span><i style={{ background: "var(--faint)" }} />Perfect prediction</span>}
      </div>
    </div>
  );
}

/** One measure per feature, largest first (a single series, so no legend). */
export function ImportanceBars({ items, format = (n) => `${Math.round(n * 100)}%` }: {
  items: { label: string; value: number }[];
  format?: (n: number) => string;
}) {
  const height = 24 + items.length * 30;
  return (
    <Sized height={height}>{(w) => (
      <BarChart width={w} height={height} data={items} layout="vertical" margin={{ top: 2, right: 40, bottom: 2, left: 8 }} barCategoryGap={6}>
        <XAxis type="number" hide domain={[0, "dataMax"]} />
        <YAxis type="category" dataKey="label" tick={{ ...axis, fill: "var(--ink)" }} width={170} axisLine={false} tickLine={false} />
        <Tooltip {...tooltipStyle} formatter={(v) => [format(Number(v)), "Importance"]} />
        <Bar dataKey="value" fill="var(--chart-1)" radius={[0, 4, 4, 0]} maxBarSize={16} isAnimationActive={false}
          label={{ position: "right", fontSize: 11, fill: "var(--muted)", formatter: (v: unknown) => format(Number(v)) }} />
      </BarChart>
    )}</Sized>
  );
}
