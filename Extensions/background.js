const API_BASE = "http://localhost:8000/api/v1";

// ── Context menu setup ────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "check-image",
    title: "🔍 Fact-check this image",
    contexts: ["image"],
  });
  chrome.contextMenus.create({
    id: "check-selection",
    title: "🔍 Fact-check selected text",
    contexts: ["selection"],
  });
  chrome.contextMenus.create({
    id: "check-page",
    title: "🔍 Fact-check this page",
    contexts: ["page", "link"],
  });
});

// ── Context menu click handler ────────────────────────────────────────────────

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  let input = "";

  if (info.menuItemId === "check-image") {
    input = info.srcUrl || "";
  } else if (info.menuItemId === "check-selection") {
    input = info.selectionText || "";
  } else if (info.menuItemId === "check-page") {
    input = info.linkUrl || tab.url || "";
  }

  if (!input.trim()) return;

  // Open side panel
  await chrome.sidePanel.open({ tabId: tab.id });

  // Submit to backend and store job_id
  await submitAndStore(input);
});

// ── Toolbar icon click — open side panel ─────────────────────────────────────

chrome.action.onClicked.addListener(async (tab) => {
  await chrome.sidePanel.open({ tabId: tab.id });
  // Signal sidepanel to show the manual input UI
  chrome.storage.session.set({ currentJobId: null, showManual: true });
});

// ── Submit to backend ─────────────────────────────────────────────────────────

async function submitAndStore(input) {
  try {
    // Tell sidepanel we're loading
    chrome.storage.session.set({ currentJobId: null, status: "submitting", input });

    const response = await fetch(`${API_BASE}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input }),
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    // Store job_id so sidepanel can poll for it
    chrome.storage.session.set({
      currentJobId: data.job_id,
      status: "polling",
      input,
      showManual: false,
    });

  } catch (err) {
    chrome.storage.session.set({
      currentJobId: null,
      status: "error",
      errorMessage: err.message,
    });
  }
}

// ── Listen for messages from sidepanel ───────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "SUBMIT_INPUT") {
    submitAndStore(msg.input).then(() => sendResponse({ ok: true }));
    return true; // keep channel open for async response
  }
});
