const API_BASE = "http://localhost:8000/api/v1";
const POLL_INTERVAL_MS = 1500;

let pollTimer    = null;
let currentJobId = null;
let sseSource    = null;

const $ = (id) => document.getElementById(id);

const SCREENS = ["idleState", "loadingState", "verdictCard", "errorState"];

function showOnly(...visible) {
  SCREENS.forEach((id) => {
    const el = $(id);
    const show = visible.includes(id);
    el.style.display = show ? "" : "none";
    el.classList.toggle("visible", show);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  showOnly("idleState");
  setupListeners();

  chrome.storage.session.get(["currentJobId", "status", "input", "errorMessage"], (data) => {
    if (data.currentJobId) {
      startTracking(data.currentJobId, data.input || "");
    } else if (data.status === "submitting") {
      showLoading("Submitting…");
    } else if (data.status === "error") {
      showError(data.errorMessage || "Unknown error");
    }
  });
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "session") return;
  if (changes.currentJobId?.newValue) {
    startTracking(changes.currentJobId.newValue, changes.input?.newValue || "");
  }
  if (changes.status?.newValue === "submitting") showLoading("Submitting…");
  if (changes.status?.newValue === "error") showError(changes.errorMessage?.newValue || "Error");
});

function showLoading(text = "Running analysis…") {
  $("loadingText").textContent = text;
  $("analyzingStrip").classList.remove("visible");
  $("analyzingStrip").style.display = "none";
  showOnly("loadingState");
}

function showAnalyzingStrip(input) {
  $("analyzingStrip").classList.add("visible");
  $("analyzingStrip").style.display = "flex";
  $("stripText").textContent = input.length > 70 ? input.slice(0, 67) + "…" : input;
}

function showError(msg) {
  $("errorMsg").textContent = msg;
  $("analyzingStrip").style.display = "none";
  showOnly("errorState");
}

function showVerdict(data) {
  $("analyzingStrip").style.display = "none";
  showOnly("verdictCard");

  const verdict = data.verdict || "UNCERTAIN";

  const banner = $("verdictBanner");
  banner.className = `verdict-banner ${verdict}`;

  const headline = $("verdictHeadline");
  headline.className = `verdict-headline ${verdict}`;
  headline.textContent = verdict.charAt(0) + verdict.slice(1).toLowerCase();

  $("confidenceNum").textContent = Math.round(data.confidence_score || 0);
  $("typeLabel").textContent = (data.input_type || "unknown").replace(/_/g, " ");

  $("summaryText").textContent = data.summary || "No summary available.";

  const flags = data.red_flags || [];
  if (flags.length > 0) {
    $("flagsSection").classList.add("visible");
    $("flagsSection").style.display = "block";
    $("flagsList").innerHTML = flags
      .map((f) => `<div class="flag-item">${f}</div>`)
      .join("");
  } else {
    $("flagsSection").classList.remove("visible");
    $("flagsSection").style.display = "none";
  }

  const sources = (data.sources || []).filter(Boolean);
  if (sources.length > 0) {
    $("sourcesSection").classList.add("visible");
    $("sourcesSection").style.display = "block";
    $("sourcesList").innerHTML = sources.map((s) => `
      <a class="source-link" href="${s}" target="_blank">
        <svg viewBox="0 0 16 16"><path d="M7 3H3a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V9"/><polyline points="10,2 14,2 14,6"/><line x1="14" y1="2" x2="7" y2="9"/></svg>
        <span>${s}</span>
      </a>`).join("");
  } else {
    $("sourcesSection").classList.remove("visible");
    $("sourcesSection").style.display = "none";
  }
}

function startTracking(jobId, input) {
  currentJobId = jobId;
  stopTracking();
  showLoading("Running analysis…");
  showAnalyzingStrip(input);
  connectSSE(jobId);
  startPolling(jobId);
}

function stopTracking() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  if (sseSource) { sseSource.close(); sseSource = null; }
}

function connectSSE(jobId) {
  try {
    sseSource = new EventSource(`${API_BASE}/stream/${jobId}`);
    sseSource.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        if (event.type === "done")  { stopTracking(); fetchVerdict(jobId); }
        if (event.type === "error") { stopTracking(); showError(event.message || "Pipeline error"); }
      } catch (_) {}
    };
    sseSource.onerror = () => { sseSource?.close(); sseSource = null; };
  } catch (_) {}
}

function startPolling(jobId) {
  pollTimer = setInterval(async () => {
    try {
      const r = await fetch(`${API_BASE}/results/${jobId}`);
      if (!r.ok) return;
      const data = await r.json();
      if (data.status === "done")  { stopTracking(); showVerdict(data); }
      else if (data.status === "error") { stopTracking(); showError(data.summary || "Analysis failed"); }
    } catch (_) {}
  }, POLL_INTERVAL_MS);
}

async function fetchVerdict(jobId) {
  try {
    const r = await fetch(`${API_BASE}/results/${jobId}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    if (data.status === "done") showVerdict(data);
    else if (data.status === "error") showError(data.summary || "Failed");
  } catch (err) {
    showError("Could not fetch results: " + err.message);
  }
}

function setupListeners() {
  $("analyzeBtn").addEventListener("click", handleSubmit);
  $("manualInput").addEventListener("keydown", (e) => { if (e.key === "Enter") handleSubmit(); });
  $("newAnalysisBtn").addEventListener("click", reset);
  $("retryBtn").addEventListener("click", reset);
}

async function handleSubmit() {
  const input = $("manualInput").value.trim();
  if (!input) return;
  $("analyzeBtn").disabled = true;
  showLoading("Submitting…");

  chrome.runtime.sendMessage({ type: "SUBMIT_INPUT", input }, (response) => {
    $("analyzeBtn").disabled = false;
    if (!response?.ok) showError("Failed to submit. Is the backend running on localhost:8000?");
  });
}

function reset() {
  stopTracking();
  currentJobId = null;
  chrome.storage.session.clear();
  $("manualInput").value = "";
  $("analyzingStrip").classList.remove("visible");
  $("analyzingStrip").style.display = "none";
  showOnly("idleState");
}
