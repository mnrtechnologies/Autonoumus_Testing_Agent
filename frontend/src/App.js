import { useState, useEffect } from "react";
import BrowserStream from "./BrowserStream";
import ChatPanel from "./ChatPanel";
import "./App.css";

function App() {
  const [mode, setMode] = useState("whitebox");
  const [url, setUrl] = useState("");
  const [goal, setGoal] = useState("");
  const [testId, setTestId] = useState(null);
  const [status, setStatus] = useState("idle");
  const [report, setReport] = useState(null);

  const startTest = async () => {
    if (!url || !goal) {
      alert("URL and Goal are required");
      return;
    }

    const res = await fetch("http://localhost:8000/tests/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode,
        url,
        goal,
        steps: []
      })
    });

    const data = await res.json();
    setTestId(data.test_id);
    setStatus("running");
    setReport(null);
  };

  // 🔄 Poll test status
  useEffect(() => {
    if (!testId) return;

    const poll = setInterval(async () => {
      const res = await fetch(
        `http://localhost:8000/tests/${testId}/status`
      );
      const data = await res.json();
      setStatus(data.status);

      if (data.status === "completed") {
        clearInterval(poll);
      }
    }, 1500);

    return () => clearInterval(poll);
  }, [testId]);

  // 📊 Fetch report after completion
  useEffect(() => {
    if (status !== "completed" || !testId) return;

    fetch(`http://localhost:8000/tests/${testId}/report`)
      .then(res => res.json())
      .then(data => setReport(data));
  }, [status, testId]);

  return (
    <div className="app-root">
      <header className="top-bar">
        <h1>🤖 Robo-Tester</h1>
        <p>Autonomous UI Testing Platform</p>
      </header>

      {!testId && (
        <div className="card">
          <h2>Create Test</h2>

          <label>Test Mode</label>
          <select value={mode} onChange={e => setMode(e.target.value)}>
            <option value="whitebox">Whitebox</option>
            <option value="blackbox">Blackbox</option>
          </select>

          <label>Target URL</label>
          <input
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://example.com"
          />

          <label>Test Goal</label>
          <textarea
            value={goal}
            onChange={e => setGoal(e.target.value)}
            placeholder="Describe what the agent should do"
          />

          <button onClick={startTest}>Start Test</button>
        </div>
      )}

      {testId && (
        <div className="layout">
          <div className="browser-pane">
            <div className="status-row">
              <span><b>Test ID:</b> {testId}</span>
              <span className={`status ${status}`}>{status}</span>
            </div>

            <BrowserStream testId={testId} />
          </div>

          {/* 🔴 Show Chat ONLY while running */}
          {status !== "completed" && (
            <ChatPanel testId={testId} status={status} />
          )}

          {/* ✅ Show Report ONLY after completion */}
          {status === "completed" && report && (
            <div className="card report">
              <h2>📊 Test Report</h2>

              <p>
                <b>Status:</b>{" "}
                {report.success ? "✅ Success" : "❌ Failed"}
              </p>

              <p>
                <b>Total Steps:</b> {report.total_steps}
              </p>

              <h3>Action History</h3>
              <ul>
                {report.action_history.map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default App;
