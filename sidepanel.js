const API_BASE = "http://localhost:8000/api/v1";
const POLL_INTERVAL_MS = 1500;

// ── State ─────────────────────────────────────────────────────────────────────
let pollTimer = null;
let currentJobId = null;
let sseSource = null;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const screens = {
  idle:     $("idleState"),
  loading:  $("loadingState"),
  pipeline: $("pipeline"),
  verdict:  $("verdictCard"),
  error:    $("errorState"),
};

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  showScreen("idle");
  setupListeners();
  // Check if background already submitted something
  chrome.storage.session.get(["currentJobId", "status", "input", "showManual"], (data) => {
    if (data.currentJobId) {
      startTracking(data.currentJobId, data.input || "");
    } else if (data.status === "submitting") {
      showLoading("Submitting...");
    } else if (data.status === "error") {
      showError(data.errorMessage || "Unknown error");
    }
  });
});

// Watch for changes from background.js
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "session") return;

  if (changes.currentJobId?.newValue) {
    const input = changes.input?.newValue || "";
    startTracking(changes.currentJobId.newValue, input);
  }

  if (changes.status?.newValue === "submitting") {
    showLoading("Submitting for analysis...");
  }

  if (changes.status?.newValue === "error") {
    showError(changes.errorMessage?.newValue || "Unknown error");
  }
});

// ── UI helpers ────────────────────────────────────────────────────────────────

function showScreen(name) {
  Object.entries(screens).forEach(([key, el]) => {
    el.classList.toggle("visible", key === name);
    el.style.display = key === name ? "" : "none";
  });
}

function showLoading(text = "Analyzing...") {
  $("loadingText").textContent = text;
  showScreen("loading");
  $("pipeline").style.display = "none";
  $("pipeline").classList.remove("visible");
  $("inputPreview").style.display = "none";
}

function showPipeline(input) {
  // Show input preview
  $("inputPreview").classList.add("visible");
  $("inputPreview").style.display = "block";
  $("previewText").textContent = input.length > 80 ? input.slice(0, 77) + "..." : input;

  // Reset all agent rows
  document.querySelectorAll(".agent-row").forEach((row) => {
    row.classList.remove("active", "done", "error");
    row.querySelector(".agent-status").textContent = "waiting";
  });

  // Show pipeline, hide others
  screens.loading.style.display = "none";
  screens.idle.style.display = "none";
  screens.verdict.style.display = "none";
  screens.error.style.display = "none";
  $("pipeline").classList.add("visible");
  $("pipeline").style.display = "block";

  // Activate triage immediately
  setAgentState("triage", "active", "running");
}

function setAgentState(agentName, state, detail = "") {
  const row = $(`agent-${agentName}`);
  if (!row) return;
  row.classList.remove("active", "done", "error");
  row.classList.add(state);
  if (detail) {
    row.querySelector(".agent-status").textContent =
      detail.length > 22 ? detail.slice(0, 20) + "…" : detail;
  }
}

function showError(msg) {
  $("errorMsg").textContent = msg;
  showScreen("error");
  $("pipeline").style.display = "none";
  $("inputPreview").style.display = "none";
}

function showVerdict(data) {
  // Hide pipeline, show verdict
  $("pipeline").style.display = "none";
  $("inputPreview").style.display = "none";
  showScreen("verdict");

  const verdict = data.verdict || "UNCERTAIN";
  const badge = $("verdictBadge");
  badge.className = `verdict-badge ${verdict}`;
  $("verdictLabel").textContent = verdict;
  $("confidenceNum").textContent = `${Math.round(data.confidence_score || 0)}%`;
  $("summaryText").textContent = data.summary || "No summary available.";
  $("typeBadge").textContent = (data.input_type || "unknown").replace("_", " ");

  // Red flags
  const flags = data.red_flags || [];
  if (flags.length > 0) {
    $("flagsBlock").classList.add("visible");
    $("flagsList").innerHTML = flags
      .map((f) => `<div class="flag-item"><span class="flag-icon">▸</span><span>${f}</span></div>`)
      .join("");
  } else {
    $("flagsBlock").classList.remove("visible");
  }

  // Sources
  const sources = data.sources || [];
  if (sources.length > 0) {
    $("sourcesBlock").classList.add("visible");
    $("sourcesList").innerHTML = sources
      .filter(Boolean)
      .map((s) => `<a class="source-link" href="${s}" target="_blank">${s}</a>`)
      .join("");
  } else {
    $("sourcesBlock").classList.remove("visible");
  }
}

// ── Tracking ──────────────────────────────────────────────────────────────────

function startTracking(jobId, input) {
  currentJobId = jobId;
  stopTracking(); // clear any previous
  showPipeline(input);
  connectSSE(jobId);
  startPolling(jobId);
}

function stopTracking() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  if (sseSource) { sseSource.close(); sseSource = null; }
}

// ── SSE — live agent updates ──────────────────────────────────────────────────

function connectSSE(jobId) {
  try {
    sseSource = new EventSource(`${API_BASE}/stream/${jobId}`);

    sseSource.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        handleSSEEvent(event);
      } catch (_) {}
    };

    sseSource.onerror = () => {
      sseSource.close();
      sseSource = null;
    };
  } catch (_) {
    // SSE failed — polling will handle it
  }
}

function handleSSEEvent(event) {
  if (event.type === "agent_update") {
    const { agent, status, detail } = event;
    const agentKey = agent.toLowerCase().replace(/\s+/g, "_");

    // Mark previous agent done
    const agentOrder = [
      "triage", "forensics", "vision", "claims",
      "claim_verifier", "fact_check", "reverse_search", "ai_text", "synthesis",
    ];
    const idx = agentOrder.indexOf(agentKey);
    if (idx > 0) setAgentState(agentOrder[idx - 1], "done", "✓");

    if (status === "running") {
      setAgentState(agentKey, "active", "running...");
    } else if (status === "done") {
      setAgentState(agentKey, "done", detail || "✓");
    } else if (status === "error") {
      setAgentState(agentKey, "error", "failed");
    }
  }

  if (event.type === "done") {
    // Mark all agents done
    document.querySelectorAll(".agent-row:not(.error)").forEach((row) => {
      if (!row.classList.contains("done")) {
        row.classList.add("done");
        row.querySelector(".agent-status").textContent = "✓";
      }
    });
    stopTracking();
    fetchVerdict(currentJobId);
  }

  if (event.type === "error") {
    stopTracking();
    showError(event.message || "Pipeline error");
  }
}

// ── Polling — fallback ────────────────────────────────────────────────────────

function startPolling(jobId) {
  pollTimer = setInterval(async () => {
    try {
      const r = await fetch(`${API_BASE}/results/${jobId}`);
      if (!r.ok) return;
      const data = await r.json();

      if (data.status === "done") {
        stopTracking();
        showVerdict(data);
      } else if (data.status === "error") {
        stopTracking();
        showError(data.summary || "Analysis failed");
      }
    } catch (err) {
      // Backend not reachable — show error after a few tries
    }
  }, POLL_INTERVAL_MS);
}

async function fetchVerdict(jobId) {
  try {
    const r = await fetch(`${API_BASE}/results/${jobId}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    if (data.status === "done") showVerdict(data);
    else if (data.status === "error") showError(data.summary || "Analysis failed");
  } catch (err) {
    showError("Could not fetch results: " + err.message);
  }
}

// ── Manual input ──────────────────────────────────────────────────────────────

function setupListeners() {
  $("analyzeBtn").addEventListener("click", handleManualSubmit);

  $("manualInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleManualSubmit();
  });

  $("newAnalysisBtn").addEventListener("click", resetToIdle);
  $("retryBtn").addEventListener("click", resetToIdle);
}

async function handleManualSubmit() {
  const input = $("manualInput").value.trim();
  if (!input) return;

  $("analyzeBtn").disabled = true;
  showLoading("Submitting for analysis...");

  chrome.runtime.sendMessage({ type: "SUBMIT_INPUT", input }, (response) => {
    $("analyzeBtn").disabled = false;
    if (!response?.ok) {
      showError("Failed to submit. Is the backend running?");
    }
  });
}

function resetToIdle() {
  stopTracking();
  currentJobId = null;
  chrome.storage.session.clear();
  $("manualInput").value = "";
  $("inputPreview").classList.remove("visible");
  $("inputPreview").style.display = "none";
  showScreen("idle");
}
