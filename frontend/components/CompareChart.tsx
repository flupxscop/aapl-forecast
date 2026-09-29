"use client";

import { useMemo } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Price } from "@/lib/api";
import { axisProps, downsample, thDate, tickFormatter, usd, yTick } from "./PriceForecastChart";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function Tip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as Price;
  return (
    <div className="tip">
      <div className="d">{thDate(label, { day: "numeric", month: "short", year: "numeric" })}</div>
      {p.open != null && <div className="r"><span>เปิด</span><b>{usd(p.open)}</b></div>}
      <div className="r"><span>ปิด</span><b>{usd(p.adjClose ?? p.close)}</b></div>
    </div>
  );
}

/** One stock's price as a soft area chart; `tone` picks blue (primary) or graphite (comparison). */
export default function CompareChart({ prices, tone, id }: { prices: Price[]; tone: "price" | "alt"; id: string }) {
  const data = useMemo(() => downsample(prices), [prices]);
  const color = tone === "price" ? "var(--s-price)" : "var(--s-alt)";
  return (
    <div className="chart sm">
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: -6 }}>
          <defs>
            <linearGradient id={`cmp-${id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={tone === "price" ? 0.28 : 0.22} />
              <stop offset="100%" stopColor={color} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--grid)" />
          <XAxis dataKey="date" {...axisProps} tickFormatter={tickFormatter(data)} minTickGap={40} tickMargin={10} />
          <YAxis {...axisProps} domain={["auto", "auto"]} width={52} tickFormatter={yTick} />
          <Tooltip content={<Tip />} cursor={{ stroke: "var(--ink-3)", strokeDasharray: "4 4" }} />
          <Area
            type="monotone" dataKey={(p: Price) => p.adjClose ?? p.close} stroke={color} strokeWidth={2}
            fill={`url(#cmp-${id})`} dot={false} isAnimationActive={false}
            activeDot={{ r: 5, fill: color, stroke: "var(--surface)", strokeWidth: 2 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
