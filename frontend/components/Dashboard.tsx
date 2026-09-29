"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CompareChart from "./CompareChart";
import PriceForecastChart, { thDate, usd } from "./PriceForecastChart";
import Sparkline from "./Sparkline";
import {
  IconArrow, IconChart, IconChevron, IconCompare, IconData, IconGrid, IconModel, IconRefresh, IconSearch, IconTable,
} from "./Icons";
import {
  api, MODEL_LABELS,
  type AppConfig, type Forecast, type ModelMetric, type Overview, type Price, type Summary,
} from "@/lib/api";

const RANGES = [
  { key: "1M", label: "1 เดือน", days: 21 },
  { key: "3M", label: "3 เดือน", days: 63 },
  { key: "6M", label: "6 เดือน", days: 126 },
  { key: "1Y", label: "1 ปี", days: 252 },
  { key: "5Y", label: "5 ปี", days: 1260 },
  { key: "ALL", label: "ทั้งหมด", days: Infinity },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];
const HORIZONS = [5, 10, 30, 60, 90];
const DEFAULT_HORIZON = 30;
const SHORT_HISTORY_DAYS = 250;
const NAV = [
  { id: "overview", label: "ภาพรวม", icon: IconGrid },
  { id: "forecast", label: "ราคาและประมาณการ", icon: IconChart },
  { id: "compare", label: "เปรียบเทียบหุ้น", icon: IconCompare },
  { id: "models", label: "ผลทดสอบแบบจำลอง", icon: IconModel },
  { id: "schedule", label: "ตารางประมาณการ", icon: IconTable },
  { id: "data", label: "จัดการข้อมูล", icon: IconData },
];

type Job = "forecast" | "prepare" | "prepare-all" | "ingest" | "train";
/** open = no key configured (local dev), locked = key required, unlocked = key accepted */
type AdminState = "unknown" | "open" | "locked" | "unlocked";
const ADMIN_KEY_STORAGE = "meridian-admin-key";
const readStoredKey = () => { try { return sessionStorage.getItem(ADMIN_KEY_STORAGE) ?? ""; } catch { return ""; } };
const storeKey = (k: string) => { try { if (k) sessionStorage.setItem(ADMIN_KEY_STORAGE, k); else sessionStorage.removeItem(ADMIN_KEY_STORAGE); } catch { /* storage unavailable */ } };

const pct = (v: number) => `${Math.abs(v).toFixed(2)}%`;
const tone = (v: number | null | undefined) => (v == null ? "muted" : v >= 0 ? "up" : "down");
const shortDate = (iso: string) => thDate(iso, { day: "numeric", month: "short", year: "2-digit" });
const sliceRange = (prices: Price[], range: RangeKey) => {
  const days = RANGES.find((r) => r.key === range)!.days;
  return Number.isFinite(days) ? prices.slice(-days) : prices;
};

function Change({ v, big = false }: { v: number | null | undefined; big?: boolean }) {
  if (v == null) return <span className="muted">—</span>;
  return (
    <span className={`chip ${tone(v)}`} style={big ? { fontSize: 12.5 } : undefined}>
      <IconArrow up={v >= 0} /> {pct(v)}
    </span>
  );
}

export default function Dashboard() {
  const [overview, setOverview] = useState<Overview[] | null>(null);
  const [symbol, setSymbol] = useState<string | null>(null);
  const [compareSym, setCompareSym] = useState<string | null>(null);

  const [prices, setPrices] = useState<Price[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [metrics, setMetrics] = useState<ModelMetric[]>([]);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [loading, setLoading] = useState(true);
  const [pricesB, setPricesB] = useState<Price[]>([]);
  const [summaryB, setSummaryB] = useState<Summary | null>(null);

  const [range, setRange] = useState<RangeKey>("6M");
  const [model, setModel] = useState("auto");
  const [horizon, setHorizon] = useState(DEFAULT_HORIZON);
  const [dataset, setDataset] = useState("");
  const [query, setQuery] = useState("");
  const [activeNav, setActiveNav] = useState("overview");

  const [job, setJob] = useState<Job | null>(null);
  const [stage, setStage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[] | null>(null);
  const [today, setToday] = useState("");
  const [adminKey, setAdminKey] = useState("");
  const [adminInput, setAdminInput] = useState("");
  const [admin, setAdmin] = useState<AdminState>("unknown");
  const [config, setConfig] = useState<AppConfig>({ mode: "live", maxHorizon: 365 });
  const [waking, setWaking] = useState(false);
  const tokenA = useRef(0);
  const tokenB = useRef(0);

  const busy = job !== null;
  const bySymbol = useMemo(() => new Map((overview ?? []).map((o) => [o.symbol, o])), [overview]);
  const current = symbol ? bySymbol.get(symbol) ?? null : null;
  const other = compareSym ? bySymbol.get(compareSym) ?? null : null;

  // ---------------------------------------------------------------- loading
  const loadOverview = useCallback(async () => {
    const ov = await api.overview();
    setOverview(ov);
    return ov;
  }, []);

  const loadSymbol = useCallback(async (sym: string) => {
    const token = ++tokenA.current; // ignore late responses for a stock the user already left
    setLoading(true);
    try {
      const [p, s, m, f] = await Promise.all([
        api.prices(sym),
        api.summary(sym).catch(() => null),
        api.metrics(sym).catch(() => [] as ModelMetric[]),
        api.latestForecast(sym).catch(() => null),
      ]);
      if (token !== tokenA.current) return;
      setPrices(p); setSummary(s); setMetrics(m); setForecast(f);
      if (f) setHorizon(f.horizon);
    } catch (e) {
      if (token === tokenA.current) setError((e as Error).message);
    } finally {
      if (token === tokenA.current) setLoading(false);
    }
  }, []);

  const loadCompare = useCallback(async (sym: string) => {
    const token = ++tokenB.current;
    const [p, s] = await Promise.all([
      api.prices(sym).catch(() => [] as Price[]),
      api.summary(sym).catch(() => null),
    ]);
    if (token !== tokenB.current) return;
    setPricesB(p); setSummaryB(s);
  }, []);

  useEffect(() => {
    // free hosting sleeps when idle: tell visitors why the first load is slow
    const wakeTimer = window.setTimeout(() => setWaking(true), 4000);
    api.config().then(setConfig).catch(() => undefined);
    const stored = readStoredKey();
    api.adminCheck(stored)
      .then((r) => { setAdminKey(stored); setAdmin(r.protectedByKey ? "unlocked" : "open"); })
      .catch(() => { storeKey(""); setAdmin("locked"); });
    setToday(new Date().toLocaleDateString("th-TH", { weekday: "short", day: "numeric", month: "long", year: "numeric" }));
    (async () => {
      try {
        const ov = await loadOverview();
        window.clearTimeout(wakeTimer);
        setWaking(false);
        const params = new URLSearchParams(window.location.search);
        const a = ov.find((o) => o.symbol === params.get("s")?.toUpperCase())?.symbol ?? ov[0]?.symbol ?? null;
        const b = ov.find((o) => o.symbol === params.get("vs")?.toUpperCase() && o.symbol !== a)?.symbol
          ?? ov.find((o) => o.symbol !== a)?.symbol ?? null;
        setSymbol(a);
        setCompareSym(b);
        if (!a) { setLoading(false); setError("ยังไม่พบรายชื่อหุ้น — ตรวจสอบว่าบริการ ml ทำงานอยู่ แล้วกดรีเฟรช"); }
      } catch (e) {
        window.clearTimeout(wakeTimer);
        setWaking(false);
        setLoading(false);
        setError((e as Error).message);
      }
    })();
    return () => window.clearTimeout(wakeTimer);
  }, [loadOverview]);

  useEffect(() => {
    if (!symbol) return;
    setModel("auto"); setDataset(""); setNotes(null); setError(null);
    loadSymbol(symbol);
  }, [symbol, loadSymbol]);

  useEffect(() => {
    if (compareSym) loadCompare(compareSym);
  }, [compareSym, loadCompare]);

  useEffect(() => {
    if (!symbol) return;
    const url = new URL(window.location.href);
    url.searchParams.set("s", symbol);
    if (compareSym) url.searchParams.set("vs", compareSym);
    window.history.replaceState(null, "", url);
  }, [symbol, compareSym]);

  // highlight the sidebar item of the section in view
  useEffect(() => {
    const els = NAV.map((n) => document.getElementById(n.id)).filter(Boolean) as HTMLElement[];
    const io = new IntersectionObserver(
      (entries) => {
        const top = entries.filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (top) setActiveNav(top.target.id);
      },
      { rootMargin: "0px 0px -65% 0px" },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [summary, overview]);

  const selectPrimary = (sym: string) => {
    if (sym === compareSym) setCompareSym(symbol); // keep the two sides different
    setSymbol(sym);
  };
  const selectCompare = (sym: string) => {
    if (sym === symbol) setSymbol(compareSym);
    setCompareSym(sym);
  };

  const refresh = async () => {
    setError(null);
    await loadOverview().catch((e) => setError((e as Error).message));
    if (symbol) await loadSymbol(symbol);
    if (compareSym) await loadCompare(compareSym);
  };

  // ---------------------------------------------------------------- actions
  const unlock = async () => {
    setError(null);
    try {
      await api.adminCheck(adminInput);
      setAdminKey(adminInput); storeKey(adminInput); setAdminInput(""); setAdmin("unlocked");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const lock = () => { setAdminKey(""); storeKey(""); setAdmin("locked"); };

  const run = async (kind: Job) => {
    if (!symbol) return;
    if (kind !== "forecast" && admin === "locked") {
      setError("งานนี้สำหรับผู้ดูแล — ใส่รหัสผู้ดูแลในส่วนจัดการข้อมูลก่อน");
      document.getElementById("data")?.scrollIntoView();
      return;
    }
    setJob(kind); setError(null); setNotes(null);
    const log: string[] = [];
    try {
      if (kind === "forecast") {
        setStage("กำลังประมาณการ");
        setForecast(await api.createForecast(symbol, model, horizon));
      } else if (kind === "prepare" || kind === "prepare-all") {
        const target = kind === "prepare" ? symbol : null;
        setStage("กำลังดึงข้อมูล");
        const ing = await api.ingest(target, adminKey);
        ing.results.forEach((r) => { if (r.notes.length) log.push(`${r.symbol}: ${r.notes.join(" · ")}`); });
        ing.errors.forEach((e) => log.push(`${e.symbol}: นำเข้าไม่สำเร็จ — ${e.error}`));
        setStage("กำลังเทรนแบบจำลอง");
        const tr = await api.train(target, adminKey);
        tr.errors.forEach((e) => log.push(`${e.symbol}: เทรนไม่สำเร็จ — ${e.error}`));
        setStage("กำลังประมาณการ");
        for (const s of Object.keys(tr.results)) {
          await api.createForecast(s, "auto", DEFAULT_HORIZON).catch((e) => log.push(`${s}: ${(e as Error).message}`));
        }
      } else if (kind === "ingest") {
        setStage("กำลังดึงข้อมูล");
        const r = await api.ingest(symbol, adminKey, dataset);
        r.results.forEach((x) => log.push(
          `${x.symbol}: ${x.rows.toLocaleString()} วันทำการ (${x.first_date} ถึง ${x.last_date}) จาก ${x.sources.join(" + ")}`
          + (x.notes.length ? ` · ${x.notes.join(" · ")}` : "")));
      } else {
        setStage("กำลังเทรนแบบจำลอง");
        const r = await api.train(symbol, adminKey);
        Object.entries(r.results).forEach(([s, runs]) => log.push(`${s}: เทรน ${runs.length} แบบจำลองแล้ว`));
      }
      if (kind === "forecast") await loadOverview(); else await refresh();
      if (log.length) setNotes(log);
    } catch (e) {
      setError((e as Error).message);
      if (log.length) setNotes(log);
    } finally {
      setJob(null); setStage("");
    }
  };

  // ---------------------------------------------------------------- derived
  const visible = useMemo(() => sliceRange(prices, range), [prices, range]);
  const visibleB = useMemo(() => sliceRange(pricesB, range), [pricesB, range]);
  const modelOptions = useMemo(() => ["auto", ...metrics.map((m) => m.model)], [metrics]);
  const best = metrics.find((m) => m.isBest);
  const lastPoint = forecast?.points[forecast.points.length - 1];
  const fcChange = lastPoint && forecast ? (lastPoint.predicted / forecast.baseClose - 1) * 100 : null;
  const hasData = summary !== null && prices.length > 0;
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !overview) return [];
    return overview.filter((o) => `${o.name} ${o.symbol} ${o.displayTicker}`.toLowerCase().includes(q)).slice(0, 6);
  }, [query, overview]);

  const footnotes: string[] = [];
  if (current && current.nativeCurrency !== "USD")
    footnotes.push(`ราคาแปลงจาก ${current.nativeCurrency} เป็น USD ด้วยอัตราแลกเปลี่ยนรายวัน ค่าประมาณการจึงรวมผลของค่าเงินด้วย`);
  if (summary && summary.rows < SHORT_HISTORY_DAYS)
    footnotes.push(`มีประวัติราคาเพียง ${summary.rows} วันทำการ จึงใช้เฉพาะแบบจำลองพื้นฐาน และช่วงความเชื่อมั่นจะกว้างกว่าปกติ`);
  if (forecast && summary && forecast.baseDate < summary.lastDate)
    footnotes.push(`ค่าประมาณการนี้ใช้ข้อมูลถึง ${shortDate(forecast.baseDate)} — กดประมาณการอีกครั้งเพื่อใช้ข้อมูลล่าสุด`);

  const batchOnly = config.mode === "precomputed";
  const canAdmin = !batchOnly && (admin === "open" || admin === "unlocked");
  const horizons = HORIZONS.filter((h) => h <= config.maxHorizon);
  const label = (k: Job, idle: string) => (job === k ? <><span className="dot" />{stage}…</> : idle);
  const rangePills = (
    <div className="pills" role="tablist" aria-label="ช่วงเวลา">
      {RANGES.map((r) => (
        <button key={r.key} role="tab" aria-selected={range === r.key} className={range === r.key ? "on" : ""}
          onClick={() => setRange(r.key)}>{r.label}</button>
      ))}
    </div>
  );
  const periodReturn = (p: Price[]) => {
    const first = p[0]; const last = p[p.length - 1];
    return ((last.adjClose ?? last.close) / (first.adjClose ?? first.close) - 1) * 100;
  };

  // ---------------------------------------------------------------- render
  return (
    <div className="app">
      {/* ============================================ sidebar */}
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark"><span /></span>Meridian</div>

        <div className="hl-card">
          <div className="hl-head">
            <span>ประมาณการ {current?.name ?? ""}</span>
            <span>{lastPoint ? shortDate(lastPoint.date) : ""}</span>
          </div>
          <div className="hl-body">
            <div className="lbl">{forecast ? `ราคาเป้าหมาย ${forecast.horizon} วันทำการ` : "ราคาเป้าหมาย"}</div>
            <div className="val num">{lastPoint ? usd(lastPoint.predicted) : "—"}</div>
            <div className="row">
              <span>{forecast ? `จาก ${usd(forecast.baseClose)}` : "ยังไม่มีค่าประมาณการ"}</span>
              {fcChange != null && (
                <span className={`tag ${fcChange < 0 ? "neg" : ""}`}>
                  <IconArrow up={fcChange >= 0} /> {pct(fcChange)}
                </span>
              )}
            </div>
          </div>
        </div>

        <nav className="nav" aria-label="ส่วนต่าง ๆ ของหน้า">
          {NAV.map(({ id, label: text, icon: Icon }) => (
            <a key={id} href={`#${id}`} className={activeNav === id ? "on" : ""} onClick={() => setActiveNav(id)}>
              <Icon />{text}
            </a>
          ))}
        </nav>

        <div className="side-foot">
          <b>แหล่งข้อมูล</b><br />Kaggle + Yahoo Finance · ราคาเป็น USD<br />
          ค่าประมาณการเพื่อการศึกษา ไม่ใช่คำแนะนำการลงทุน
        </div>
      </aside>

      {/* ============================================ main */}
      <main className="main">
        <div className="topbar">
          <div className="search">
            <IconSearch />
            <input
              value={query} onChange={(e) => setQuery(e.target.value)} placeholder="ค้นหาหุ้น เช่น NVIDIA, META"
              aria-label="ค้นหาหุ้น"
              onKeyDown={(e) => {
                if (e.key === "Enter" && matches[0]) { selectPrimary(matches[0].symbol); setQuery(""); }
                if (e.key === "Escape") setQuery("");
              }}
            />
            {matches.length > 0 && (
              <ul className="results">
                {matches.map((m, i) => (
                  <li key={m.symbol}>
                    <button className={i === 0 ? "hi" : ""} onClick={() => { selectPrimary(m.symbol); setQuery(""); }}>
                      <span><b>{m.displayTicker}</b> <span className="muted">{m.name}</span></span>
                      <span className="num">{m.lastClose != null ? usd(m.lastClose) : ""}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="top-right">
            <span className="date">{today}</span>
            <button className="icon-btn" onClick={refresh} disabled={busy} aria-label="รีเฟรช" title="รีเฟรช">
              <span className={loading ? "spin" : ""} style={{ display: "grid" }}><IconRefresh /></span>
            </button>
          </div>
        </div>

        {waking && (
          <div className="notice" role="status">
            กำลังปลุกเซิร์ฟเวอร์ — เว็บนี้ใช้โฮสติ้งฟรีที่หลับเมื่อไม่มีผู้ใช้ ครั้งแรกอาจรอได้ถึง 1 นาที
          </div>
        )}
        {error && <div className="notice error" role="alert">{error}</div>}
        {notes && <div className="notice">{notes.map((n, i) => <div key={i}>{n}</div>)}</div>}

        {/* ---------- stock picker */}
        <section className="card">
          <h3>เลือกหุ้นเพื่อดูและเปรียบเทียบ</h3>
          <div className="picker">
            <div className="pick">
              <label htmlFor="pickA">หุ้นหลัก</label>
              <select id="pickA" value={symbol ?? ""} onChange={(e) => selectPrimary(e.target.value)}>
                {(overview ?? []).map((o) => <option key={o.symbol} value={o.symbol}>{o.name} ({o.displayTicker})</option>)}
              </select>
              <IconChevron />
            </div>
            <div className="pick">
              <label htmlFor="pickB">เปรียบเทียบกับ</label>
              <select id="pickB" value={compareSym ?? ""} onChange={(e) => selectCompare(e.target.value)}>
                {(overview ?? []).map((o) => <option key={o.symbol} value={o.symbol}>{o.name} ({o.displayTicker})</option>)}
              </select>
              <IconChevron />
            </div>
            <a className="btn" href="#compare" onClick={() => setActiveNav("compare")}>เปรียบเทียบ</a>
          </div>
        </section>

        {/* ---------- overview */}
        <div className="h-row" id="overview">
          <h2>ภาพรวม</h2>
          <span className="muted" style={{ fontSize: 12.5 }}>คลิกการ์ดเพื่อเลือกเป็นหุ้นหลัก</span>
        </div>
        <div className="ov-row">
          {(overview ?? Array.from({ length: 5 }, () => null)).map((o, i) =>
            o ? (
              <button key={o.symbol} onClick={() => selectPrimary(o.symbol)}
                className={`ov ${o.symbol === symbol ? "on" : o.symbol === compareSym ? "alt" : ""}`}
                aria-pressed={o.symbol === symbol}>
                <div className="ov-top">
                  <span className="mono">{o.name.charAt(0)}</span>
                  <div className="ov-id"><b>{o.displayTicker}</b><span>{o.name}</span></div>
                  <Sparkline values={o.spark ?? []} width={70} height={30} />
                </div>
                <div className="ov-stats">
                  <div><small>ราคาล่าสุด</small><b className="num">{o.lastClose != null ? usd(o.lastClose) : "—"}</b></div>
                  <div><small>เปลี่ยนแปลง</small><Change v={o.changePct} /></div>
                  <div style={{ textAlign: "right" }}>
                    <small>{o.forecastHorizon ? `คาด ${o.forecastHorizon} วัน` : "คาดการณ์"}</small>
                    <Change v={o.forecastChangePct} />
                  </div>
                </div>
              </button>
            ) : (
              <div key={i} className="ov" aria-hidden="true">
                <div className="sk" style={{ height: 40, width: "60%" }} />
                <div className="sk" style={{ height: 30 }} />
              </div>
            ),
          )}
        </div>

        {/* ---------- empty / loading states for the primary stock */}
        {current && !hasData && !loading && (
          <section className="card empty" style={{ marginTop: 24 }}>
            <h3>ยังไม่มีข้อมูลของ {current.name}</h3>
            {canAdmin ? (
              <>
                <p>ระบบจะดึงข้อมูลย้อนหลังจาก Kaggle เติมข้อมูลล่าสุดจาก Yahoo Finance ทดสอบแบบจำลองทุกตัว
                  แล้วสร้างค่าประมาณการ {DEFAULT_HORIZON} วันทำการให้ทันที</p>
                <div className="acts">
                  <button className="btn" onClick={() => run("prepare-all")} disabled={busy}>{label("prepare-all", "เตรียมข้อมูลทุกหุ้น")}</button>
                  <button className="btn ghost" onClick={() => run("prepare")} disabled={busy}>{label("prepare", `เฉพาะ ${current.name}`)}</button>
                </div>
              </>
            ) : (
              <p>ข้อมูลของหุ้นนี้กำลังเตรียมอยู่ ระบบอัปเดตข้อมูลอัตโนมัติทุกวัน ลองกลับมาดูอีกครั้งภายหลัง</p>
            )}
          </section>
        )}
        {loading && !hasData && (
          <section className="card" style={{ marginTop: 24 }} aria-busy="true">
            <div className="sk" style={{ height: 22, width: 180 }} />
            <div className="sk" style={{ height: 320, marginTop: 20 }} />
          </section>
        )}

        {hasData && summary && current && (
          <>
            {/* ---------- price & forecast */}
            <div className="h-row" id="forecast"><h2>ราคาและประมาณการ</h2>{rangePills}</div>
            <section className="card">
              <div className="sc-head">
                <div className="id"><b>{current.displayTicker}</b><span>{current.name} · {current.exchange}</span></div>
                <div className="px">
                  <Change v={summary.changePct} big />
                  <span className="big num">{usd(summary.lastClose)}</span>
                  <small>ข้อมูลล่าสุด {shortDate(summary.lastDate)}</small>
                </div>
              </div>

              <div className="stats">
                <div className="stat">
                  <small>{forecast ? `ประมาณการ ${forecast.horizon} วันทำการ` : "ประมาณการ"}</small>
                  <b className="num">{lastPoint ? usd(lastPoint.predicted) : "—"}</b>{" "}
                  {fcChange != null && <Change v={fcChange} />}
                </div>
                <div className="stat">
                  <small>ช่วงความเชื่อมั่น 95%</small>
                  <b className="num">{lastPoint ? `${usd(lastPoint.lower)} – ${usd(lastPoint.upper)}` : "—"}</b>
                </div>
                <div className="stat">
                  <small>ช่วง 52 สัปดาห์</small>
                  <b className="num">{usd(summary.low52w)} – {usd(summary.high52w)}</b>
                </div>
                <div className="stat">
                  <small>แบบจำลองที่ใช้</small>
                  <b>{forecast ? MODEL_LABELS[forecast.model] ?? forecast.model : best ? MODEL_LABELS[best.model] ?? best.model : "—"}</b>
                </div>
              </div>

              <PriceForecastChart prices={visible} forecast={forecast} />
              <div className="legend">
                <span><i className="lg-price" />ราคาปิด</span>
                {forecast && <span><i className="lg-fc" />ค่าประมาณการ</span>}
                {forecast && <span><i className="lg-band" />ช่วงความเชื่อมั่น 95%</span>}
                {forecast?.points.some((p) => p.actual != null) && <span><i className="lg-act" />ราคาจริงหลังประมาณการ</span>}
              </div>
              {footnotes.map((f, i) => <div key={i} className="note-line">{f}</div>)}

              <div className="controls">
                <span className="lbl">แบบจำลอง</span>
                <select className="select-pill" value={model} onChange={(e) => setModel(e.target.value)} disabled={!metrics.length}>
                  {modelOptions.map((k) => <option key={k} value={k}>{MODEL_LABELS[k] ?? k}</option>)}
                </select>
                <span className="lbl" style={{ marginLeft: 8 }}>ล่วงหน้า</span>
                <div className="pills" role="group" aria-label="จำนวนวันทำการ">
                  {horizons.map((h) => (
                    <button key={h} className={horizon === h ? "on" : ""} onClick={() => setHorizon(h)}>{h} วัน</button>
                  ))}
                </div>
                <span className="spacer" />
                {metrics.length ? (
                  <button className="btn sm" onClick={() => run("forecast")} disabled={busy}>{label("forecast", "ประมาณการ")}</button>
                ) : canAdmin ? (
                  <button className="btn sm" onClick={() => run("prepare")} disabled={busy}>{label("prepare", "เทรนและประมาณการ")}</button>
                ) : (
                  <span className="muted" style={{ fontSize: 12.5 }}>ยังไม่มีแบบจำลองสำหรับหุ้นนี้</span>
                )}
              </div>
            </section>

            {/* ---------- comparison */}
            <div className="h-row" id="compare"><h2>เปรียบเทียบราคา</h2>{rangePills}</div>
            <div className="grid2">
              {[
                { o: current, s: summary, p: visible, t: "price" as const },
                { o: other, s: summaryB, p: visibleB, t: "alt" as const },
              ].map(({ o, s, p, t }, i) => (
                <section className="card" key={i}>
                  {o && s && p.length ? (
                    <>
                      <div className="sc-head">
                        <div className="id"><b>{o.displayTicker}</b><span>{o.name}</span></div>
                        <div className="px">
                          <Change v={s.changePct} />
                          <span className="big num">{usd(s.lastClose)}</span>
                          <small>ข้อมูลล่าสุด {shortDate(s.lastDate)}</small>
                        </div>
                      </div>
                      <CompareChart prices={p} tone={t} id={`${i}`} />
                      <p className="caption">
                        ผลตอบแทนช่วงนี้ <b className={tone(periodReturn(p))}>
                          {periodReturn(p) >= 0 ? "+" : "−"}{pct(periodReturn(p))}</b> ตั้งแต่ {shortDate(p[0].date)}
                      </p>
                    </>
                  ) : (
                    <div className="empty" style={{ padding: "60px 10px" }}>
                      <p style={{ margin: 0 }}>{o ? `ยังไม่มีข้อมูลของ ${o.name}` : "เลือกหุ้นเพื่อเปรียบเทียบ"}</p>
                    </div>
                  )}
                </section>
              ))}
            </div>

            {/* ---------- ledgers */}
            <div className="grid2" style={{ marginTop: 30 }}>
              <section className="card" id="models" style={{ scrollMarginTop: 16 }}>
                <h3>ผลทดสอบแบบจำลอง</h3>
                {metrics.length === 0 ? <p className="muted">ยังไม่มีผลทดสอบ</p> : (
                  <>
                    <div className="scroll" style={{ maxHeight: "none" }}>
                      <table>
                        <thead><tr><th>แบบจำลอง</th><th>MAPE</th><th>RMSE</th><th>ทิศทางถูก</th></tr></thead>
                        <tbody>
                          {metrics.map((m) => (
                            <tr key={m.model} className={m.isBest ? "best" : ""}>
                              <td>
                                {MODEL_LABELS[m.model] ?? m.model}
                                {m.isBest && <span className="chip up" style={{ marginLeft: 8 }}>ดีที่สุด</span>}
                              </td>
                              <td>{m.mape?.toFixed(2)}%</td>
                              <td>{m.rmse?.toFixed(2)}</td>
                              <td>{m.directionAcc?.toFixed(1)}%</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <p className="caption">
                      ทดสอบย้อนหลัง {metrics[0].testDays} วันทำการ ประมาณการล่วงหน้า 1–5 วันจากทุกจุด · เทรนเมื่อ{" "}
                      {new Date(metrics[0].trainedAt).toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short" })}
                    </p>
                  </>
                )}
              </section>

              <section className="card" id="schedule" style={{ scrollMarginTop: 16 }}>
                <h3>ตารางค่าประมาณการ</h3>
                {!forecast ? <p className="muted">ยังไม่มีค่าประมาณการ</p> : (
                  <div className="scroll">
                    <table>
                      <thead><tr><th>วันที่</th><th>ประมาณการ</th><th>ช่วง 95%</th><th>ราคาจริง</th></tr></thead>
                      <tbody>
                        {forecast.points.map((p) => (
                          <tr key={p.step}>
                            <td>{shortDate(p.date)}</td>
                            <td>{usd(p.predicted)}</td>
                            <td className="muted">{usd(p.lower)} – {usd(p.upper)}</td>
                            <td>{p.actual != null ? usd(p.actual) : <span className="muted">—</span>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </div>
          </>
        )}

        {/* ---------- data management */}
        <div className="h-row" id="data"><h2>จัดการข้อมูล</h2></div>
        <section className="card">
          {batchOnly && (
            <p className="caption" style={{ marginTop: 0 }}>
              ข้อมูล แบบจำลอง และค่าประมาณการอัปเดตอัตโนมัติทุกวันเวลา 05:30 น. (เวลาไทย)
              ผ่าน GitHub Actions — ผู้ดูแลสั่งอัปเดตทันทีได้ที่ปุ่ม <b>Run workflow</b> ในแท็บ Actions ของ repository
            </p>
          )}
          {!batchOnly && admin === "locked" && (
            <form className="data-row" style={{ marginTop: 0 }} onSubmit={(e) => { e.preventDefault(); unlock(); }}>
              <span className="muted" style={{ fontSize: 12.5, flexBasis: "100%" }}>
                ข้อมูลอัปเดตอัตโนมัติทุกวัน ส่วนการนำเข้าและเทรนด้วยตนเองสำหรับผู้ดูแลเท่านั้น
              </span>
              <input className="text-input" type="password" autoComplete="current-password" value={adminInput}
                onChange={(e) => setAdminInput(e.target.value)} placeholder="รหัสผู้ดูแล" aria-label="รหัสผู้ดูแล"
                style={{ flex: "0 1 280px" }} />
              <button className="btn sm" type="submit" disabled={!adminInput}>ปลดล็อก</button>
            </form>
          )}
          {canAdmin && (<>
          <div className="data-row" style={{ marginTop: 0 }}>
            <button className="btn" onClick={() => run("prepare-all")} disabled={busy}>{label("prepare-all", "อัปเดตทุกหุ้น")}</button>
            <span className="muted" style={{ fontSize: 12.5 }}>
              ดึงข้อมูลล่าสุด เทรนใหม่ และประมาณการ {DEFAULT_HORIZON} วันสำหรับทุกหุ้น (ประมาณ 1–3 นาที)
            </span>
          </div>
          {current && (
            <div className="data-row">
              <b style={{ minWidth: 110 }}>{current.name}</b>
              <input className="text-input" value={dataset} onChange={(e) => setDataset(e.target.value)}
                placeholder="แหล่งข้อมูลอื่น: owner/dataset, ลิงก์ kaggle.com/datasets/… หรือลิงก์ไฟล์ CSV" />
              <button className="btn sm ghost" onClick={() => run("ingest")} disabled={busy}>{label("ingest", "นำเข้า")}</button>
              <button className="btn sm ghost" onClick={() => run("train")} disabled={busy || !hasData}>{label("train", "เทรน")}</button>
            </div>
          )}
          {admin === "unlocked" && (
            <div className="data-row">
              <span className="muted" style={{ fontSize: 12.5 }}>เข้าสู่โหมดผู้ดูแลแล้ว</span>
              <button className="btn sm ghost" onClick={lock}>ออกจากโหมดผู้ดูแล</button>
            </div>
          )}
          </>)}
          {summary && current && (
            <p className="caption">
              {current.name} มีข้อมูล {summary.rows.toLocaleString()} วันทำการ ตั้งแต่ {shortDate(summary.firstDate)}
              {current.nativeCurrency !== "USD" && ` · แปลงจาก ${current.nativeCurrency}`}
            </p>
          )}
        </section>

        <p className="foot">ค่าประมาณการจากแบบจำลองทางสถิติเพื่อการศึกษาเท่านั้น ไม่ใช่คำแนะนำการลงทุน</p>
      </main>
    </div>
  );
}
