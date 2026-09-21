/* SikandX Android app logic — talks to private bot server or shared demo feed. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  };

  const state = {
    mode: store.get("sx_mode", "private"),
    privateUrl: store.get("sx_private", ""),
    demoUrl: store.get("sx_demo", ""),
    chat: [],
  };

  function base() {
    const u = (state.mode === "demo" ? state.demoUrl : state.privateUrl) || "";
    return u.trim().replace(/\/+$/, "");
  }
  function isDemo() { return state.mode === "demo"; }

  function pill(text, live) {
    const p = $("connPill");
    p.textContent = text;
    p.classList.toggle("live", !!live);
  }

  async function api(path, opts) {
    const b = base();
    if (!b) throw new Error("No server URL — open Settings first.");
    const r = await fetch(b + path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts || {}));
    if (!r.ok) throw new Error("Server " + r.status);
    return r.json();
  }

  function say(role, text) {
    state.chat.push({ role, text: String(text).slice(0, 600) });
    state.chat = state.chat.slice(-50);
    renderChat();
  }
  function renderChat() {
    const box = $("chatBox");
    if (!state.chat.length) return;
    box.innerHTML = state.chat.map((m) =>
      m.role === "user" ? `<div class="umsg"><span></span></div>` : `<div class="bmsg"><span></span></div>`
    ).join("");
    [...box.children].forEach((div, i) => { div.firstChild.textContent = state.chat[i].text; });
    box.scrollTop = box.scrollHeight;
  }

  // tabs
  document.querySelectorAll(".tab").forEach((t) => {
    t.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
      document.querySelectorAll(".view").forEach((x) => x.classList.remove("active"));
      t.classList.add("active");
      $(t.dataset.v).classList.add("active");
    });
  });

  // quick command chips
  const quick = ["status", "go long on gold", "go short on gold", "close all positions", "pause", "resume", "set target 500", "enable auto", "disable auto"];
  $("quickChips").innerHTML = quick.map((q) => `<button class="chip" data-q="${q}">${q}</button>`).join("");
  document.querySelectorAll("[data-q]").forEach((b) =>
    b.addEventListener("click", () => { $("cmdText").value = b.dataset.q; sendCmd(); }));

  async function refresh() {
    const box = $("statusBox");
    try {
      const j = await api(isDemo() ? "/api/demo-signal" : "/api/status", isDemo() ? { method: "POST", body: JSON.stringify({}) } : {});
      if (isDemo()) {
        pill("DEMO FEED", true);
        box.innerHTML = `<div class="kv"><span>Mode</span><b>Shared demo</b></div>
          <div class="kv"><span>Symbol</span><b>XAUUSD</b></div>
          <div class="kv"><span>Sample price</span><b>${j.price}</b></div>
          <div class="kv"><span>Signal</span><b class="${j.side === "buy" ? "buy" : j.side === "sell" ? "sell" : ""}">${(j.side || "NO TRADE").toUpperCase()}</b></div>`;
        $("miniSignal").innerHTML = signalHtml(j);
      } else {
        const open = j.acct ? j.acct.open : 0;
        pill(j.broker && j.broker.connected ? "CONNECTED" : "SERVER OK", !!(j.broker && j.broker.connected));
        box.innerHTML = `
          <div class="kv"><span>Balance base</span><b>${j.cfg.balance}</b></div>
          <div class="kv"><span>Equity target</span><b>${j.cfg.target}</b></div>
          <div class="kv"><span>Max positions</span><b>${j.cfg.max_positions}</b></div>
          <div class="kv"><span>Broker</span><b>${j.broker.connected ? "connected" : "validation mode"}</b></div>
          <div class="kv"><span>Open positions</span><b>${open}</b></div>
          <div class="kv"><span>Paused</span><b>${j.flags.paused}</b></div>
          <div class="kv"><span>Halted @ target</span><b>${j.flags.halted}</b></div>
          <div class="kv"><span>Auto</span><b>${j.flags.auto}</b></div>
          ${j.backtest ? `<div class="kv"><span>Backtest equity</span><b>${j.backtest.equity}</b></div>` : ""}`;
        if (j.signal) $("miniSignal").innerHTML = signalHtml(Object.assign({ src: "" }, j.signal));
      }
      store.set("sx_last_ok", new Date().toISOString());
    } catch (e) {
      pill("OFFLINE", false);
      box.innerHTML = `<div class="warn">Cannot reach server: ${esc(e.message)}. Check the URL, Wi-Fi (same network for private server), and that the bot is running.</div>`;
    }
  }

  function signalHtml(j) {
    if (!j) return `<div class="mut">No scan yet.</div>`;
    const cls = j.side === "buy" ? "buy" : j.side === "sell" ? "sell" : "gold";
    return `<div class="big ${cls}">${((j.side || "NO TRADE")).toUpperCase()}</div>
      <div>${j.price !== undefined ? j.price : ""} • score ${j.score !== undefined ? j.score : "—"} • <span class="gold">${esc(j.bias_label || "")}</span></div>
      ${j.side ? `<div class="mut">SL ${j.sl} • TP ${j.tp}</div>` : ""}
      <div class="mut">${esc((j.reasons || []).join(" • "))}</div>
      ${j.src ? `<div class="mut">${esc(j.src)}</div>` : ""}`;
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c])); }

  async function scan() {
    const box = $("signalBox");
    box.innerHTML = `<div class="mut">Scanning…</div>`;
    try {
      const path = isDemo() ? "/api/demo-signal" : "/api/signal";
      const j = await api(path, { method: "POST", body: JSON.stringify({}) });
      if (!j.ok) throw new Error(j.error || "scan failed");
      box.innerHTML = signalHtml(j);
      $("miniSignal").innerHTML = signalHtml(j);
      pill(isDemo() ? "DEMO FEED" : "SERVER OK", true);
    } catch (e) {
      box.innerHTML = `<div class="warn">Scan failed: ${esc(e.message)}</div>`;
    }
  }

  async function backtest() {
    const box = $("btBox");
    box.innerHTML = `<div class="mut">Running…</div>`;
    const payload = {
      balance: +$("fBalance").value || 100,
      target: +$("fTarget").value || 300,
      max_positions: +$("fMax").value || 5,
      min_score: +$("fScore").value || 45,
      bars: +$("fBars").value || 600,
    };
    try {
      const path = isDemo() ? "/api/demo-backtest" : "/api/backtest";
      const j = await api(path, { method: "POST", body: JSON.stringify(payload) });
      if (!j.ok) throw new Error(j.error || "backtest failed");
      box.innerHTML = `<div class="big gold">${j.equity} <span class="mut" style="font-size:15px">/ ${j.target}</span></div>
        <div>${j.trades} trades • ${j.wins} wins • ${j.win_rate}% • realized ${j.realized}</div>
        <div>${j.halted ? `<b class="gold">HALTED at target — resume to continue</b>` : `<span class="mut">open ${j.open} • ${j.bars} bars</span>`}</div>`;
    } catch (e) {
      box.innerHTML = `<div class="warn">Backtest failed: ${esc(e.message)}</div>`;
    }
  }

  async function sendCmd() {
    const t = $("cmdText").value.trim();
    if (!t) return;
    say("user", t);
    $("cmdText").value = "";
    if (isDemo()) {
      say("bot", "Demo server is read-only. Connect your private bot server in Settings to run commands.");
      return;
    }
    try {
      const j = await api("/api/command", { method: "POST", body: JSON.stringify({ text: t }) });
      say("bot", j.reply || "OK");
    } catch (e) {
      say("bot", "Failed: " + e.message);
    }
  }

  function saveSettings(fromBoot) {
    state.mode = $("sMode").value;
    state.privateUrl = $("sPrivate").value.trim();
    state.demoUrl = $("sDemo").value.trim();
    store.set("sx_mode", state.mode);
    store.set("sx_private", state.privateUrl);
    store.set("sx_demo", state.demoUrl);
    $("demoWarn").style.display = state.mode === "demo" ? "block" : "none";
    if (!fromBoot) {
      $("setMsg").innerHTML = `<div class="note">Saved. Contacting ${esc(base() || "(no URL)")}…</div>`;
      refresh();
    }
  }

  // init
  $("sMode").value = state.mode;
  $("sPrivate").value = state.privateUrl;
  $("sDemo").value = state.demoUrl;
  $("demoWarn").style.display = state.mode === "demo" ? "block" : "none";
  $("btnRefresh").addEventListener("click", refresh);
  $("btnSignal").addEventListener("click", scan);
  $("btnBacktest").addEventListener("click", backtest);
  $("btnSend").addEventListener("click", sendCmd);
  $("cmdText").addEventListener("keydown", (e) => { if (e.key === "Enter") sendCmd(); });
  $("btnSave").addEventListener("click", () => saveSettings(false));
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("./sw.js").catch(() => {});
  pill(base() ? "SAVED — TAP REFRESH" : "OFFLINE", false);
})();
