import { useState, useEffect, useRef, useCallback } from "react";

const API = "http://localhost:8000";
const WS  = "ws://localhost:8000";

// ── Colour tokens ────────────────────────────────────────────────────────────
const C = {
  bg:       "#0a0c10",
  surface:  "#111318",
  border:   "#1e2330",
  accent:   "#00e5ff",
  accent2:  "#7c3aed",
  green:    "#22d3a5",
  yellow:   "#f59e0b",
  red:      "#ef4444",
  text:     "#e2e8f0",
  muted:    "#64748b",
};

// ── Tiny helpers ─────────────────────────────────────────────────────────────
const cx = (...cls) => cls.filter(Boolean).join(" ");

function useInterval(cb, delay) {
  const saved = useRef(cb);
  useEffect(() => { saved.current = cb; }, [cb]);
  useEffect(() => {
    if (delay === null) return;
    const id = setInterval(() => saved.current(), delay);
    return () => clearInterval(id);
  }, [delay]);
}

// ── Global CSS injected once ──────────────────────────────────────────────────
const GLOBAL_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Syne:wght@400;600;700;800&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: ${C.bg};
    color: ${C.text};
    font-family: 'JetBrains Mono', monospace;
    min-height: 100vh;
    overflow-x: hidden;
  }

  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-track { background: ${C.bg}; }
  ::-webkit-scrollbar-thumb { background: ${C.border}; border-radius: 2px; }

  @keyframes pulse-ring {
    0%   { box-shadow: 0 0 0 0 rgba(0,229,255,.4); }
    70%  { box-shadow: 0 0 0 10px rgba(0,229,255,0); }
    100% { box-shadow: 0 0 0 0 rgba(0,229,255,0); }
  }
  @keyframes scan {
    0%   { transform: translateY(-100%); }
    100% { transform: translateY(100vh); }
  }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
  @keyframes fadeUp {
    from { opacity:0; transform:translateY(12px); }
    to   { opacity:1; transform:translateY(0); }
  }
  @keyframes shimmer {
    0%   { background-position: -200% center; }
    100% { background-position:  200% center; }
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  .fade-up { animation: fadeUp .35s ease both; }

  .btn {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 10px 20px; border-radius: 6px; border: none;
    font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 600;
    cursor: pointer; transition: all .18s ease; letter-spacing: .04em;
    text-transform: uppercase;
  }
  .btn:disabled { opacity: .4; cursor: not-allowed; }
  .btn-primary {
    background: ${C.accent}; color: #000;
  }
  .btn-primary:hover:not(:disabled) {
    background: #33eaff; box-shadow: 0 0 20px rgba(0,229,255,.35);
  }
  .btn-ghost {
    background: transparent; color: ${C.muted};
    border: 1px solid ${C.border};
  }
  .btn-ghost:hover:not(:disabled) { border-color: ${C.accent}; color: ${C.accent}; }

  .btn-danger {
    background: transparent; color: ${C.red};
    border: 1px solid ${C.red};
  }
  .btn-danger:hover:not(:disabled) { background: ${C.red}; color: #fff; }

  .input {
    width: 100%; padding: 10px 14px; border-radius: 6px;
    background: ${C.bg}; border: 1px solid ${C.border};
    color: ${C.text}; font-family: 'JetBrains Mono', monospace; font-size: 13px;
    outline: none; transition: border-color .18s;
  }
  .input:focus { border-color: ${C.accent}; }
  .input::placeholder { color: ${C.muted}; }

  .label {
    display: block; font-size: 11px; color: ${C.muted};
    text-transform: uppercase; letter-spacing: .08em; margin-bottom: 6px;
  }

  .badge {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: .06em;
  }
  .badge-running  { background: rgba(0,229,255,.1);  color: ${C.accent};  border: 1px solid rgba(0,229,255,.25); }
  .badge-done     { background: rgba(34,211,165,.1); color: ${C.green};   border: 1px solid rgba(34,211,165,.25); }
  .badge-failed   { background: rgba(239,68,68,.1);  color: ${C.red};     border: 1px solid rgba(239,68,68,.25); }
  .badge-idle     { background: rgba(100,116,139,.1);color: ${C.muted};   border: 1px solid rgba(100,116,139,.25); }

  .card {
    background: ${C.surface}; border: 1px solid ${C.border};
    border-radius: 10px; padding: 20px;
  }

  .progress-bar-track {
    height: 4px; background: ${C.border}; border-radius: 2px; overflow: hidden;
  }
  .progress-bar-fill {
    height: 100%; border-radius: 2px;
    background: linear-gradient(90deg, ${C.accent}, ${C.accent2});
    transition: width .4s ease;
  }

  .log-line {
    font-size: 12px; line-height: 1.7; padding: 2px 0;
    border-bottom: 1px solid rgba(30,35,48,.6);
  }
  .log-cyan   { color: ${C.accent}; }
  .log-green  { color: ${C.green}; }
  .log-yellow { color: ${C.yellow}; }
  .log-red    { color: ${C.red}; }
  .log-white  { color: ${C.text}; }

  .screen-wrap {
    position: relative; border-radius: 8px; overflow: hidden;
    border: 1px solid ${C.border}; background: #000;
    aspect-ratio: 16/9;
  }
  .screen-wrap img {
    width: 100%; height: 100%; object-fit: contain; display: block;
  }
  .screen-placeholder {
    width: 100%; height: 100%; display: flex; align-items: center;
    justify-content: center; flex-direction: column; gap: 12px;
    color: ${C.muted}; font-size: 13px;
  }
  .scan-line {
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, transparent, ${C.accent}, transparent);
    animation: scan 2s linear infinite; pointer-events: none; opacity: .6;
  }

  .phase-header {
    font-family: 'Syne', sans-serif; font-weight: 800;
    font-size: 11px; text-transform: uppercase; letter-spacing: .14em;
    color: ${C.muted}; margin-bottom: 4px;
  }
  .phase-title {
    font-family: 'Syne', sans-serif; font-weight: 700; font-size: 22px;
    color: ${C.text}; line-height: 1.2;
  }

  .toggle-group {
    display: flex; border: 1px solid ${C.border}; border-radius: 8px; overflow: hidden;
  }
  .toggle-opt {
    flex: 1; padding: 10px; text-align: center; cursor: pointer;
    font-size: 12px; font-weight: 600; text-transform: uppercase;
    letter-spacing: .07em; transition: all .18s; color: ${C.muted};
    border: none; background: transparent; font-family: 'JetBrains Mono', monospace;
  }
  .toggle-opt.active {
    background: ${C.accent}; color: #000;
  }
  .toggle-opt:not(.active):hover { color: ${C.text}; background: rgba(255,255,255,.04); }

  .divider {
    height: 1px; background: ${C.border}; margin: 20px 0;
  }

  .stat-row { display: flex; align-items: center; justify-content: space-between; }
  .stat-val { font-size: 20px; font-weight: 700; color: ${C.accent}; }
  .stat-lbl { font-size: 11px; color: ${C.muted}; text-transform: uppercase; letter-spacing: .06em; }

  .step-dot {
    width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
  }
  .dot-done    { background: ${C.green}; }
  .dot-active  { background: ${C.accent}; animation: pulse-ring 1.5s infinite; }
  .dot-pending { background: ${C.border}; }

  .cursor { animation: blink 1s step-end infinite; }

  .nav-tab {
    padding: 8px 18px; font-size: 12px; font-weight: 600;
    text-transform: uppercase; letter-spacing: .07em;
    border: none; background: transparent; cursor: pointer;
    font-family: 'JetBrains Mono', monospace;
    border-bottom: 2px solid transparent; transition: all .18s;
    color: ${C.muted};
  }
  .nav-tab.active { color: ${C.accent}; border-bottom-color: ${C.accent}; }
  .nav-tab:hover:not(.active) { color: ${C.text}; }

  .excel-btn {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 10px 18px; border-radius: 6px;
    background: rgba(34,211,165,.1); color: ${C.green};
    border: 1px solid rgba(34,211,165,.3);
    font-family: 'JetBrains Mono', monospace; font-size: 13px;
    font-weight: 600; cursor: pointer; transition: all .18s;
    text-transform: uppercase; letter-spacing: .04em;
  }
  .excel-btn:hover { background: rgba(34,211,165,.2); box-shadow: 0 0 16px rgba(34,211,165,.2); }

  .spinner {
    width: 16px; height: 16px; border-radius: 50%;
    border: 2px solid rgba(0,229,255,.2); border-top-color: ${C.accent};
    animation: spin .7s linear infinite; display: inline-block;
  }
`;

// ── Phase Steps sidebar ───────────────────────────────────────────────────────
const PHASES = [
  { id: "login",   label: "Phase 0", sub: "Authentication" },
  { id: "phase2",  label: "Phase 1", sub: "Discovery / Semantic" },
  { id: "phase3",  label: "Phase 2", sub: "Validation" },
];

function Sidebar({ phase }) {
  return (
    <div style={{ width: 200, flexShrink: 0, padding: "32px 20px", borderRight: `1px solid ${C.border}`, display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontFamily: "'Syne',sans-serif", fontWeight: 800, fontSize: 15, color: C.text, marginBottom: 24, letterSpacing: ".02em" }}>
        ROBO<span style={{ color: C.accent }}>TESTER</span>
      </div>
      {PHASES.map((p, i) => {
        const idx   = PHASES.findIndex(x => x.id === phase);
        const myIdx = i;
        const done    = myIdx < idx;
        const active  = myIdx === idx;
        const pending = myIdx > idx;
        return (
          <div key={p.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 12px", borderRadius: 8, background: active ? "rgba(0,229,255,.06)" : "transparent", border: active ? `1px solid rgba(0,229,255,.15)` : "1px solid transparent" }}>
            <div className={cx("step-dot", done ? "dot-done" : active ? "dot-active" : "dot-pending")} />
            <div>
              <div style={{ fontSize: 10, color: done ? C.green : active ? C.accent : C.muted, textTransform: "uppercase", letterSpacing: ".09em", fontWeight: 600 }}>{p.label}</div>
              <div style={{ fontSize: 12, color: done ? C.green : active ? C.text : C.muted, marginTop: 1 }}>{p.sub}</div>
            </div>
          </div>
        );
      })}

      <div style={{ marginTop: "auto", paddingTop: 20, borderTop: `1px solid ${C.border}` }}>
        <button className="btn btn-danger" style={{ width: "100%", justifyContent: "center", fontSize: 11 }}
          onClick={() => fetch(`${API}/terminate`, { method: "POST" })}>
          ⏹ Terminate
        </button>
      </div>
    </div>
  );
}

// ── Live Screenshot panel ─────────────────────────────────────────────────────
function ScreenPanel({ src, label, scanning = true }) {
  return (
    <div>
      {label && <div className="label" style={{ marginBottom: 8 }}>{label}</div>}
      <div className="screen-wrap">
        {src
          ? <img src={src} alt="live screenshot" />
          : <div className="screen-placeholder">
              <div className="spinner" style={{ width: 28, height: 28 }} />
              <span>Waiting for browser…</span>
            </div>
        }
        {scanning && <div className="scan-line" />}
      </div>
    </div>
  );
}

// ── Log panel ─────────────────────────────────────────────────────────────────
function LogPanel({ logs }) {
  const ref = useRef(null);
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [logs]);
  return (
    <div ref={ref} style={{ height: 220, overflowY: "auto", padding: "10px 14px", background: C.bg, borderRadius: 8, border: `1px solid ${C.border}` }}>
      {logs.length === 0
        ? <div style={{ color: C.muted, fontSize: 12 }}>Waiting for logs…<span className="cursor">_</span></div>
        : logs.map((l, i) => (
            <div key={i} className={cx("log-line", `log-${l.color || "white"}`)}>
              <span style={{ color: C.muted, marginRight: 8, userSelect: "none" }}>{String(i + 1).padStart(3, "0")}</span>
              {l.message}
            </div>
          ))
      }
    </div>
  );
}

// ── Progress bar ──────────────────────────────────────────────────────────────
function ProgressBar({ value = 0, max = 100, label }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div>
      {label && (
        <div className="stat-row" style={{ marginBottom: 6 }}>
          <span style={{ fontSize: 12, color: C.muted }}>{label}</span>
          <span style={{ fontSize: 12, color: C.accent, fontWeight: 700 }}>{value} / {max} <span style={{ color: C.muted }}>({pct}%)</span></span>
        </div>
      )}
      <div className="progress-bar-track">
        <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// PHASE 0 — Login
// ════════════════════════════════════════════════════════════════════════════
function PhaseLogin({ onDone }) {
  const [email,     setEmail]     = useState("");
  const [password,  setPassword]  = useState("");
  const [otp,       setOtp]       = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  const [mode,      setMode]      = useState("checking"); // "checking" | "semantic"
  const [status,    setStatus]    = useState("idle");     // idle | connecting | running | done | error
  const [logs,      setLogs]      = useState([]);
  const [screenshot,setScreenshot]= useState(null);
  const [needOtp,   setNeedOtp]   = useState(false);
  const [liveOtp,   setLiveOtp]   = useState("");
  const wsRef = useRef(null);

  const pushLog = (msg, color = "white") =>
    setLogs(p => [...p, { message: msg, color }]);

  const connect = () => {
    if (!email || !targetUrl) return;
    setStatus("connecting");
    setLogs([]);
    setScreenshot(null);

    const ws = new WebSocket(`${WS}/ws/login`);
    wsRef.current = ws;

    ws.onopen = () => setStatus("running");

    ws.onmessage = (ev) => {
      const data = JSON.parse(ev.data);

      if (data.type === "connected") {
        pushLog(data.message, "cyan");
        ws.send(JSON.stringify({ email, password: password || undefined, otp: otp || undefined, target_url: targetUrl }));
        return;
      }
      if (data.type === "log")        { pushLog(data.message, data.color || "white"); return; }
      if (data.type === "screenshot") { setScreenshot(`data:image/png;base64,${data.data}`); return; }
      if (data.type === "input_needed" && data.field === "otp") { setNeedOtp(true); return; }
      if (data.type === "done") {
        pushLog("✅ Login complete — auth.json saved", "green");
        setStatus("done");
        ws.close();
        setTimeout(() => onDone(targetUrl, mode), 800);
        return;
      }
      if (data.type === "error") { pushLog(`✗ ${data.message}`, "red"); setStatus("error"); }
    };

    ws.onerror = () => { pushLog("WebSocket error", "red"); setStatus("error"); };
    ws.onclose = () => { if (status === "running") pushLog("Connection closed", "yellow"); };
  };

  const sendOtp = () => {
    if (!liveOtp || !wsRef.current) return;
    wsRef.current.send(JSON.stringify({ otp: liveOtp }));
    pushLog(`OTP sent: ${liveOtp}`, "green");
    setNeedOtp(false);
    setLiveOtp("");
  };

  return (
    <div className="fade-up" style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <div className="phase-header">Phase 0</div>
        <div className="phase-title">Authentication</div>
        <div style={{ fontSize: 13, color: C.muted, marginTop: 6 }}>
          Login via AI agent — screenshots stream live below
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {/* Left — form */}
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div>
            <label className="label">Target URL *</label>
            <input className="input" placeholder="https://staging.example.com/sign-in" value={targetUrl} onChange={e => setTargetUrl(e.target.value)} disabled={status === "running"} />
          </div>
          <div>
            <label className="label">Email *</label>
            <input className="input" placeholder="user@example.com" value={email} onChange={e => setEmail(e.target.value)} disabled={status === "running"} />
          </div>
          <div>
            <label className="label">Password <span style={{ color: C.muted }}>(optional)</span></label>
            <input className="input" type="password" placeholder="••••••••" value={password} onChange={e => setPassword(e.target.value)} disabled={status === "running"} />
          </div>
          <div>
            <label className="label">OTP / Passcode <span style={{ color: C.muted }}>(optional — pre-fill if known)</span></label>
            <input className="input" placeholder="123456" value={otp} onChange={e => setOtp(e.target.value)} disabled={status === "running"} />
          </div>

          <div className="divider" style={{ margin: "4px 0" }} />

          <div>
            <label className="label">After login — run</label>
            <div className="toggle-group">
              <button className={cx("toggle-opt", mode === "checking" ? "active" : "")} onClick={() => setMode("checking")} disabled={status === "running"}>
                🔍 Checking
              </button>
              <button className={cx("toggle-opt", mode === "semantic" ? "active" : "")} onClick={() => setMode("semantic")} disabled={status === "running"}>
                🧠 Semantic
              </button>
            </div>
          </div>

          <button className="btn btn-primary" style={{ marginTop: 4, justifyContent: "center" }}
            onClick={connect} disabled={!email || !targetUrl || status === "running" || status === "done"}>
            {status === "connecting" ? <><span className="spinner" /> Connecting…</>
             : status === "running"   ? <><span className="spinner" /> Agent running…</>
             : status === "done"      ? "✓ Done"
             : "▶ Start Login Agent"}
          </button>

          {needOtp && (
            <div className="fade-up" style={{ padding: 12, borderRadius: 8, background: "rgba(245,158,11,.08)", border: `1px solid rgba(245,158,11,.25)` }}>
              <div style={{ fontSize: 12, color: C.yellow, marginBottom: 8, fontWeight: 600 }}>⚡ OTP Required</div>
              <div style={{ display: "flex", gap: 8 }}>
                <input className="input" placeholder="Enter OTP" value={liveOtp} onChange={e => setLiveOtp(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && sendOtp()}
                  style={{ flex: 1 }} />
                <button className="btn btn-primary" onClick={sendOtp}>Send</button>
              </div>
            </div>
          )}
        </div>

        {/* Right — live feed */}
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 12, color: C.muted, textTransform: "uppercase", letterSpacing: ".07em" }}>Live Browser</span>
            <span className={cx("badge", status === "running" ? "badge-running" : status === "done" ? "badge-done" : "badge-idle")}>
              {status === "running" && <span className="spinner" style={{ width: 8, height: 8 }} />}
              {status}
            </span>
          </div>
          <ScreenPanel src={screenshot} scanning={status === "running"} />
          <LogPanel logs={logs} />
        </div>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// PHASE 2 — Checking Pipeline
// ════════════════════════════════════════════════════════════════════════════
function PhaseChecking({ targetUrl, onPhase3 }) {
  const [jobId,      setJobId]      = useState(null);
  const [status,     setStatus]     = useState("starting");
  const [screenshot, setScreenshot] = useState(null);
  const [logs,       setLogs]       = useState([]);
  const [progress,   setProgress]   = useState({ total: 0, completed: 0, current: "" });
  const wsRef = useRef(null);

  const pushLog = (msg, color = "white") => setLogs(p => [...p, { message: msg, color }]);

  useEffect(() => {
    let cancelled = false;

    const start = async () => {
      pushLog(`Starting Checking Pipeline → ${targetUrl}`, "cyan");
      const res = await fetch(`${API}/checking/start`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base_url: targetUrl }),
      });
      const data = await res.json();
      if (cancelled) return;

      setJobId(data.job_id);
      pushLog(`Job ID: ${data.job_id}`, "cyan");

      // Connect WS
      const ws = new WebSocket(`${WS}/ws/checking/${data.job_id}`);
      wsRef.current = ws;

      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "frame") {
          setScreenshot(`data:image/jpeg;base64,${msg.image}`);
          if (msg.current_url) setProgress(p => ({ ...p, current: msg.current_url }));
          if (msg.total)       setProgress(p => ({ ...p, total: msg.total }));
          if (msg.completed !== undefined) setProgress(p => ({ ...p, completed: msg.completed }));
          return;
        }
        if (msg.type === "url_report") {
          pushLog(`✓ ${msg.url}`, "green");
          setProgress(p => ({ ...p, completed: msg.completed || p.completed, total: msg.total || p.total }));
          return;
        }
        if (msg.message) pushLog(msg.message, msg.type === "error" ? "red" : msg.type === "done" ? "green" : "white");
        if (msg.type === "done") {
          setStatus("done");
          pushLog("Checking complete — triggering Phase 3 validation…", "cyan");
          ws.close();
          // Auto trigger phase 3
          triggerPhase3(data.job_id);
        }
        if (msg.type === "error") { setStatus("error"); }
      };

      ws.onerror = () => pushLog("WS error", "red");
      setStatus("running");
    };

    start().catch(e => pushLog(String(e), "red"));
    return () => { cancelled = true; wsRef.current?.close(); };
  }, []);

  // Poll status for progress numbers
  useInterval(async () => {
    if (!jobId || status !== "running") return;
    try {
      const r = await fetch(`${API}/checking/${jobId}/status`);
      const d = await r.json();
      setProgress({ total: d.total_urls, completed: d.completed_urls, current: d.current_url || "" });
    } catch {}
  }, status === "running" ? 3000 : null);

  const triggerPhase3 = async (jid) => {
    try {
      const r = await fetch(`${API}/checking/${jid}/trigger-all-tests`, { method: "POST" });
      const d = await r.json();
      pushLog(`Phase 3 batch started — ${d.total_tasks} tasks`, "cyan");
      onPhase3("checking", jid);
    } catch (e) { pushLog(`Phase 3 trigger failed: ${e}`, "red"); }
  };

  return (
    <div className="fade-up" style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <div className="phase-header">Phase 1 — Checking</div>
          <div className="phase-title">Discovery & Crawling</div>
        </div>
        <span className={cx("badge", status === "running" ? "badge-running" : status === "done" ? "badge-done" : "badge-failed")}>
          {status === "running" && <span className="spinner" style={{ width: 8, height: 8 }} />}
          {status}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card">
            <div style={{ display: "flex", gap: 20, marginBottom: 16 }}>
              <div>
                <div className="stat-val">{progress.completed}</div>
                <div className="stat-lbl">Completed</div>
              </div>
              <div>
                <div className="stat-val">{progress.total || "—"}</div>
                <div className="stat-lbl">Total URLs</div>
              </div>
            </div>
            <ProgressBar value={progress.completed} max={progress.total || 1} label="URL Progress" />
            {progress.current && (
              <div style={{ marginTop: 10, fontSize: 11, color: C.muted, wordBreak: "break-all" }}>
                <span style={{ color: C.accent }}>►</span> {progress.current}
              </div>
            )}
          </div>
          <LogPanel logs={logs} />
        </div>
        <ScreenPanel src={screenshot} scanning={status === "running"} label="Live Browser" />
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// PHASE 2 — Semantic Driver
// ════════════════════════════════════════════════════════════════════════════
function PhaseSemantic({ targetUrl, onPhase3 }) {
  const [testId,     setTestId]     = useState(null);
  const [status,     setStatus]     = useState("starting");
  const [screenshot, setScreenshot] = useState(null);
  const [logs,       setLogs]       = useState([]);
  const [step,       setStep]       = useState(0);
  const [excelB64,   setExcelB64]   = useState(null);
  const [excelName,  setExcelName]  = useState(null);
  const wsRef = useRef(null);

  const pushLog = (msg, color = "white") => setLogs(p => [...p, { message: msg, color }]);

  useEffect(() => {
    let cancelled = false;

    const start = async () => {
      pushLog(`Starting Semantic Driver → ${targetUrl}`, "cyan");
      const res = await fetch(`${API}/semantic/start`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: targetUrl }),
      });
      const data = await res.json();
      if (cancelled) return;

      setTestId(data.test_id);
      pushLog(`Test ID: ${data.test_id}`, "cyan");

      const ws = new WebSocket(`${WS}/ws/semantic/${data.test_id}`);
      wsRef.current = ws;

      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "frame") {
          setScreenshot(`data:image/jpeg;base64,${msg.image}`);
          if (msg.step !== undefined) setStep(msg.step);
          return;
        }
        if (msg.message) pushLog(msg.message, msg.type === "error" ? "red" : msg.type === "done" ? "green" : "white");
        if (msg.type === "done") {
          setStatus("done");
          if (msg.excel_base64) { setExcelB64(msg.excel_base64); setExcelName(msg.excel_filename); }
          ws.close();
          // Auto trigger convert + phase 3
          triggerConvert(data.test_id);
        }
        if (msg.type === "error") setStatus("error");
      };

      ws.onerror = () => pushLog("WS error", "red");
      setStatus("running");
    };

    start().catch(e => pushLog(String(e), "red"));
    return () => { cancelled = true; wsRef.current?.close(); };
  }, []);

  const triggerConvert = async (tid) => {
    try {
      pushLog("Converting stories → Orchestrator tasks…", "cyan");
      const r = await fetch(`${API}/semantic/${tid}/convert-to-orchestrator`, { method: "POST" });
      const d = await r.json();
      pushLog(`Phase 3 batch started — ${d.total_tasks} tasks`, "cyan");
      onPhase3("semantic", tid);
    } catch (e) { pushLog(`Convert failed: ${e}`, "red"); }
  };

  const downloadExcel = () => {
    if (!excelB64 || !excelName) return;
    const link = document.createElement("a");
    link.href = `data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,${excelB64}`;
    link.download = excelName;
    link.click();
  };

  return (
    <div className="fade-up" style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <div className="phase-header">Phase 1 — Semantic</div>
          <div className="phase-title">Autonomous Exploration</div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {excelB64 && (
            <button className="excel-btn" onClick={downloadExcel}>
              ⬇ Download Report
            </button>
          )}
          <span className={cx("badge", status === "running" ? "badge-running" : status === "done" ? "badge-done" : "badge-failed")}>
            {status === "running" && <span className="spinner" style={{ width: 8, height: 8 }} />}
            {status}
          </span>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card">
            <div style={{ display: "flex", gap: 20 }}>
              <div>
                <div className="stat-val">{step}</div>
                <div className="stat-lbl">Steps taken</div>
              </div>
              <div>
                <div className="stat-val" style={{ color: status === "done" ? C.green : C.accent }}>
                  {status === "done" ? "✓" : <span className="spinner" style={{ width: 18, height: 18 }} />}
                </div>
                <div className="stat-lbl">Status</div>
              </div>
            </div>
          </div>
          <LogPanel logs={logs} />
        </div>
        <ScreenPanel src={screenshot} scanning={status === "running"} label="Live Browser" />
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// PHASE 3 — Validation (Sequential test runner)
// ════════════════════════════════════════════════════════════════════════════
function PhaseValidation({ source }) {
  // Polls /tests to find newly created test IDs and streams /ws/tests/{id}
  const [tests,       setTests]       = useState([]); // [{id, status}]
  const [activeId,    setActiveId]    = useState(null);
  const [screenshot,  setScreenshot]  = useState(null);
  const [logs,        setLogs]        = useState([]);
  const wsRef        = useRef(null);
  const knownIds     = useRef(new Set());
  const activeWsRef  = useRef(null);

  const pushLog = (msg, color = "white") => setLogs(p => [...p, { message: msg, color }]);

  // Poll /tests for new IDs
  useInterval(async () => {
    try {
      const r = await fetch(`${API}/tests`);
      const d = await r.json();
      const ids = Object.keys(d);
      const fresh = ids.filter(id => !knownIds.current.has(id));
      fresh.forEach(id => {
        knownIds.current.add(id);
        setTests(p => [...p, { id, status: d[id].status }]);
        pushLog(`New test: ${id}`, "cyan");
      });
      // Update statuses
      setTests(p => p.map(t => ({ ...t, status: d[t.id]?.status || t.status })));
    } catch {}
  }, 4000);

  // When a new test appears or active finishes, connect to its WS
  useEffect(() => {
    const running = tests.find(t => t.status === "running");
    if (!running) return;
    if (running.id === activeId) return;

    setActiveId(running.id);
    activeWsRef.current?.close();

    const ws = new WebSocket(`${WS}/ws/tests/${running.id}`);
    activeWsRef.current = ws;

    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "frame") {
        setScreenshot(`data:image/jpeg;base64,${msg.image}`);
        return;
      }
      if (msg.message) pushLog(msg.message, "white");
    };

    ws.onerror = () => pushLog(`WS error on ${running.id}`, "red");

    return () => ws.close();
  }, [tests]);

  const done    = tests.filter(t => t.status === "completed").length;
  const failed  = tests.filter(t => t.status === "failed").length;
  const total   = tests.length;

  return (
    <div className="fade-up" style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <div className="phase-header">Phase 2 — Validation</div>
        <div className="phase-title">Sequential Test Execution</div>
        <div style={{ fontSize: 13, color: C.muted, marginTop: 4 }}>Source: {source}</div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {/* Stats */}
          <div className="card" style={{ display: "flex", gap: 24 }}>
            <div><div className="stat-val">{total}</div><div className="stat-lbl">Total</div></div>
            <div><div className="stat-val" style={{ color: C.green }}>{done}</div><div className="stat-lbl">Passed</div></div>
            <div><div className="stat-val" style={{ color: C.red }}>{failed}</div><div className="stat-lbl">Failed</div></div>
          </div>

          {total > 0 && <ProgressBar value={done + failed} max={total} label="Overall Progress" />}

          {/* Test list */}
          <div style={{ maxHeight: 260, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
            {tests.map(t => (
              <div key={t.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", borderRadius: 6, background: t.id === activeId ? "rgba(0,229,255,.06)" : C.surface, border: `1px solid ${t.id === activeId ? "rgba(0,229,255,.2)" : C.border}`, fontSize: 12 }}>
                <span className={cx("step-dot", t.status === "completed" ? "dot-done" : t.status === "failed" ? "" : "dot-active")} style={t.status === "failed" ? { background: C.red } : {}} />
                <span style={{ color: C.muted, flex: 1, fontFamily: "monospace" }}>{t.id}</span>
                <span className={cx("badge", t.status === "completed" ? "badge-done" : t.status === "failed" ? "badge-failed" : "badge-running")} style={{ fontSize: 10, padding: "2px 8px" }}>
                  {t.status}
                </span>
              </div>
            ))}
            {tests.length === 0 && (
              <div style={{ color: C.muted, fontSize: 12, padding: 12 }}>
                Waiting for tests to be created…<span className="cursor">_</span>
              </div>
            )}
          </div>

          <LogPanel logs={logs} />
        </div>

        <ScreenPanel src={screenshot} scanning={!!activeId} label={activeId ? `Live — ${activeId}` : "Live Browser"} />
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// ROOT APP
// ════════════════════════════════════════════════════════════════════════════
export default function App() {
  // phase: "login" | "phase2" | "phase3"
  const [phase,     setPhase]     = useState("login");
  const [targetUrl, setTargetUrl] = useState("");
  const [mode,      setMode]      = useState("checking"); // chosen in login
  const [p3Source,  setP3Source]  = useState("");

  const handleLoginDone = (url, selectedMode) => {
    setTargetUrl(url);
    setMode(selectedMode);
    setPhase("phase2");
  };

  const handlePhase3 = (source, id) => {
    setP3Source(`${source} / ${id}`);
    setPhase("phase3");
  };

  const currentPhase = phase === "login" ? "login" : phase === "phase2" ? "phase2" : "phase3";

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: GLOBAL_CSS }} />
      <div style={{ display: "flex", minHeight: "100vh" }}>
        <Sidebar phase={currentPhase} />

        <div style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>
          {/* Top bar */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 28 }}>
            <div style={{ display: "flex", gap: 0, borderBottom: `1px solid ${C.border}` }}>
              {["login", "phase2", "phase3"].map((p, i) => (
                <button key={p} className={cx("nav-tab", phase === p ? "active" : "")}
                  onClick={() => setPhase(p)}
                  disabled={p === "phase2" && !targetUrl || p === "phase3" && !p3Source}>
                  {["Phase 0 — Login", "Phase 1 — Discovery", "Phase 2 — Validation"][i]}
                </button>
              ))}
            </div>

            <div style={{ fontSize: 11, color: C.muted }}>
              {targetUrl && <span style={{ color: C.accent }}>► </span>}
              {targetUrl || "No URL set"}
            </div>
          </div>

          {/* Phase content */}
          {phase === "login" && <PhaseLogin onDone={handleLoginDone} />}

          {phase === "phase2" && targetUrl && mode === "checking" && (
            <PhaseChecking targetUrl={targetUrl} onPhase3={handlePhase3} />
          )}
          {phase === "phase2" && targetUrl && mode === "semantic" && (
            <PhaseSemantic targetUrl={targetUrl} onPhase3={handlePhase3} />
          )}

          {phase === "phase3" && <PhaseValidation source={p3Source} />}
        </div>
      </div>
    </>
  );
}