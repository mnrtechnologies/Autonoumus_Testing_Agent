const API_BASE = "http://localhost:8000";

export async function startTest() {
  const res = await fetch(`${API_BASE}/tests/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode: "blackbox",
      url: "https://www.mnrtechnologies.com",
      goal: "Explore services",
      headless: true
    })
  });

  return res.json();
}

export async function getStatus(testId) {
  const res = await fetch(`${API_BASE}/tests/${testId}/status`);
  return res.json();
}
