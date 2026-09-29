"use client";

import { useMemo } from "react";
import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { Forecast, Price } from "@/lib/api";

type Row = { date: string; price?: number; predicted?: number; band?: [number, number]; actual?: number };

const MAX_POINTS = 1200;
export const usd = (v: number) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
export const thDate = (iso: string, opts: Intl.DateTimeFormatOptions) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("th-TH", opts);

export function downsample(prices: Price[]) {
  const stride = Math.max(1, Math.ceil(prices.length / MAX_POINTS));
  return prices.filter((_, i) => i % stride === 0 || i === prices.length - 1);
}

export function tickFormatter(rows: { date: string }[]) {
  const first = rows[0]?.date;
  const last = rows[rows.length - 1]?.date;
  const days = first && last ? (Date.parse(last) - Date.parse(first)) / 86_400_000 : 0;
  return (iso: string) =>
    days > 540 ? thDate(iso, { month: "short", year: "2-digit" }) : thDate(iso, { day: "numeric", month: "short" });
}

export const axisProps = {
  tick: { fill: "var(--ink-3)", fontSize: 11 },
  tickLine: false,
  axisLine: false,
} as const;

export const yTick = (v: number) => `$${v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toFixed(0)}`;

// Dark rounded bubble, like the rest of the UI's tooltips.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const row: Row = payload[0].payload;
  const lines: [string, string][] = [];
  if (row.price != null) lines.push(["ราคาปิด", usd(row.price)]);
  if (row.predicted != null && row.price == null) lines.push(["ประมาณการ", usd(row.predicted)]);
  if (row.band && row.price == null) lines.push(["ช่วง 95%", `${usd(row.band[0])} – ${usd(row.band[1])}`]);
  if (row.actual != null) lines.push(["ราคาจริง", usd(row.actual)]);
  return (
    <div className="tip">
      <div className="d">{thDate(label, { day: "numeric", month: "short", year: "numeric" })}</div>
      {lines.map(([k, v]) => <div className="r" key={k}><span>{k}</span><b>{v}</b></div>)}
    </div>
  );
}

export default function PriceForecastChart({ prices, forecast }: { prices: Price[]; forecast: Forecast | null }) {
  const data = useMemo<Row[]>(() => {
    const rows: Row[] = downsample(prices).map((p) => ({ date: p.date, price: p.adjClose ?? p.close }));
    if (forecast && rows.length) {
      const last = rows[rows.length - 1];
      if (last.date === forecast.baseDate) {  // anchor the forecast on the last close
        last.predicted = forecast.baseClose;
        last.band = [forecast.baseClose, forecast.baseClose];
      }
      for (const p of forecast.points) {
        rows.push({ date: p.date, predicted: p.predicted, band: [p.lower, p.upper], actual: p.actual ?? undefined });
      }
    }
    return rows;
  }, [prices, forecast]);

  return (
    <div className="chart" role="img" aria-label="กราฟราคาปิดและค่าประมาณการพร้อมช่วงความเชื่อมั่น 95%">
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: -6 }}>
          <defs>
            <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--s-price)" stopOpacity={0.28} />
              <stop offset="100%" stopColor="var(--s-price)" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--grid)" />
          <XAxis dataKey="date" {...axisProps} tickFormatter={tickFormatter(data)} minTickGap={48} tickMargin={10} />
          <YAxis {...axisProps} domain={["auto", "auto"]} width={56} tickFormatter={yTick} />
          <Tooltip content={<ChartTooltip />} cursor={{ stroke: "var(--ink-3)", strokeDasharray: "4 4" }} />
          {forecast && <ReferenceLine x={forecast.baseDate} stroke="var(--ink-3)" strokeDasharray="4 4" />}
          <Area type="monotone" dataKey="band" stroke="none" fill="var(--s-band)" isAnimationActive={false} />
          <Area
            type="monotone" dataKey="price" stroke="var(--s-price)" strokeWidth={2} fill="url(#priceFill)"
            dot={false} activeDot={{ r: 5, fill: "var(--s-price)", stroke: "var(--surface)", strokeWidth: 2 }}
            isAnimationActive={false}
          />
          <Line
            type="monotone" dataKey="predicted" stroke="var(--s-fc)" strokeWidth={2} strokeDasharray="6 5"
            dot={false} activeDot={{ r: 5, fill: "var(--s-fc)", stroke: "var(--surface)", strokeWidth: 2 }}
            isAnimationActive={false}
          />
          <Line
            type="monotone" dataKey="actual" stroke="none"
            dot={{ r: 4, fill: "var(--s-act)", stroke: "var(--surface)", strokeWidth: 2 }}
            activeDot={{ r: 5, fill: "var(--s-act)", stroke: "var(--surface)", strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
