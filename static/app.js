(() => {
  "use strict";
  const MAX_PDF = 10 * 1024 * 1024;
  const HISTORY_KEY = "extractor_history";
  const $ = (id) => document.getElementById(id);
  const tabs = ["url", "pdf", "history"];
  let lastName = "extracted";

  // ---- Tabs ----
  function showTab(name) {
    tabs.forEach((t) => {
      const on = t === name;
      $("tab-" + t).setAttribute("aria-selected", on);
      $("tab-" + t).tabIndex = on ? 0 : -1;
      $("panel-" + t).hidden = !on;
    });
    if (name === "history") renderHistory();
  }
  tabs.forEach((t) => $("tab-" + t).addEventListener("click", () => showTab(t)));

  // ---- Status and result ----
  function status(msg, type = "") {
    const s = $("status");
    s.textContent = msg;
    s.className = type;
  }
  function showResult(text, name) {
    lastName = name;
    $("output").textContent = text; // textContent only: extracted text can never run as code
    $("result").hidden = false;
  }
  function busy(btn, on) { btn.disabled = on; }

  // ---- API ----
  async function send(path, options, btn, label) {
    busy(btn, true);
    $("result").hidden = true;
    status("Extracting...");
    try {
      const res = await fetch(path, { ...options, credentials: "same-origin" });
      let data = {};
      try { data = await res.json(); } catch { /* non-JSON error */ }
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Something went wrong. Try again.");
      showResult(data.text, label);
      addHistory(path.includes("pdf") ? "PDF" : "Article", label);
      status("Done. " + data.text.length.toLocaleString() + " characters extracted.", "ok");
    } catch (err) {
      status(err.message || "Network error. Check your connection.", "error");
    } finally {
      busy(btn, false);
    }
  }

  $("url-go").addEventListener("click", () => {
    const value = $("url-input").value.trim();
    let u;
    try { u = new URL(value); } catch { return status("Enter a full link starting with https://", "error"); }
    if (!["http:", "https:"].includes(u.protocol)) return status("Only http and https links are allowed.", "error");
    send("/api/extract/url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: value }),
    }, $("url-go"), u.hostname);
  });

  $("pdf-go").addEventListener("click", () => {
    const file = $("pdf-input").files[0];
    if (!file) return status("Choose a PDF file first.", "error");
    if (!/\.pdf$/i.test(file.name)) return status("That file is not a PDF.", "error");
    if (file.size > MAX_PDF) return status("PDF is too large (max 10 MB).", "error");
    const form = new FormData();
    form.append("file", file);
    send("/api/extract/pdf", { method: "POST", body: form }, $("pdf-go"), file.name.replace(/\.pdf$/i, ""));
  });

  // ---- Copy and download ----
  $("copy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("output").textContent);
      status("Copied to clipboard.", "ok");
    } catch { status("Could not copy. Select the text and copy manually.", "error"); }
  });
  $("download").addEventListener("click", () => {
    const blob = new Blob([$("output").textContent], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = lastName.replace(/[^\w.-]+/g, "_").slice(0, 60) + ".txt";
    a.click();
    URL.revokeObjectURL(a.href);
  });

  // ---- History (browser only, source names only) ----
  function loadHistory() {
    try {
      const list = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
      return Array.isArray(list) ? list.filter((i) => i && typeof i.name === "string") : [];
    } catch { return []; }
  }
  function addHistory(kind, name) {
    const list = loadHistory();
    list.unshift({ kind, name: String(name).slice(0, 120), time: new Date().toISOString() });
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, 20))); } catch { /* storage full or blocked */ }
  }
  function renderHistory() {
    const list = loadHistory();
    const ol = $("history-list");
    ol.replaceChildren();
    list.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item.kind + ": " + item.name;
      const t = document.createElement("time");
      const d = new Date(item.time);
      t.textContent = isNaN(d) ? "" : d.toLocaleString();
      li.append(t);
      ol.append(li);
    });
    $("history-empty").hidden = list.length > 0;
    $("history-clear").hidden = list.length === 0;
  }
  $("history-clear").addEventListener("click", () => {
    try { localStorage.removeItem(HISTORY_KEY); } catch { /* ignore */ }
    renderHistory();
  });
})();
