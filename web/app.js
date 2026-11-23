/* hinddian dashboard — 流水线 / 草稿 */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const TABS = ["pipeline", "drafts"];
  const state = { tab: "pipeline", overview: null, batch: null };

  async function api(path) {
    const res = await fetch(path, { headers: { Accept: "application/json" } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `${res.status}`);
    return data;
  }
  function toast(msg) {
    const t = $("toast");
    t.textContent = msg; t.className = "toast bad"; t.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 3500);
  }
  const setText = (id, v) => { $(id).textContent = v == null ? "—" : v; };
  const empty = (msg, err) => `<p class="empty${err ? " err" : ""}">${esc(msg)}</p>`;
  const chip = (text, cls = "") => `<span class="chip ${esc(cls)}">${esc(text)}</span>`;
  const when = (iso) => new Date(iso).toLocaleString("zh-CN", { hour12: false, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
  function md(text) {
    const lines = esc(text || "").replace(/`([^`]+)`/g, "<code>$1</code>").split("\n");
    let html = "", inList = false;
    for (const line of lines) {
      const item = line.match(/^\s*[-*]\s+(.*)$/);
      if (item) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${item[1]}</li>`; continue; }
      if (inList) { html += "</ul>"; inList = false; }
      if (line.trim()) html += `<p>${line}</p>`;
    }
    return html + (inList ? "</ul>" : "");
  }
  const projects = () => state.batch?.projects || [];
  const pendingCount = () => projects().reduce((count, project) => count + project.drafts, 0);

  function route() {
    const tab = (location.hash || "#pipeline").slice(1);
    state.tab = TABS.includes(tab) ? tab : "pipeline";
    for (const t of TABS) $("view-" + t).hidden = t !== state.tab;
    document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === state.tab));
    load(state.tab);
  }
  async function load(tab) {
    try {
      if (tab === "pipeline") await loadPipeline();
      else await loadDrafts();
    } catch (e) { toast(e.message); }
  }

  function box(el, stage) {
    const r = el.getBoundingClientRect(), s = stage.getBoundingClientRect();
    const l = r.left - s.left, t = r.top - s.top;
    return { l, t, r: l + r.width, b: t + r.height, cx: l + r.width / 2, cy: t + r.height / 2 };
  }
  function wirePath(a, b) {
    if (b.t >= a.b - 4) {
      const y = a.b + (b.t - a.b) / 2;
      return { d: `M${a.cx},${a.b} C${a.cx},${y} ${b.cx},${y} ${b.cx},${b.t}`, lx: (a.cx + b.cx) / 2, ly: y };
    }
    const x = a.r + (b.l - a.r) / 2;
    return { d: `M${a.r},${a.cy} C${x},${a.cy} ${x},${b.cy} ${b.l},${b.cy}`, lx: x, ly: (a.cy + b.cy) / 2 };
  }
  const width = (n) => n > 0 ? Math.min(5, 1.4 + Math.log10(n + 1) * 1.3) : 1.2;
  function drawWires() {
    const stage = $("stage"), svg = $("wires");
    if (!stage.offsetParent) return;
    svg.innerHTML = "";
    const node = (key) => stage.querySelector(`[data-n="${key}"]`);
    const drafts = state.overview?.drafts;
    const pending = state.batch ? pendingCount() : null;
    const edges = [
      { f: "hooks", t: "jev", col: "c-muted", plain: true },
      { f: "jev", t: "drafts", n: drafts?.ok ? drafts.total + drafts.processed : null, col: "c-accent" },
      { f: "drafts", t: "analysis", n: pending, col: "c-accent", live: true },
      { f: "analysis", t: "obsidian", n: drafts?.ok ? drafts.processed : null, col: "c-green" },
    ];
    for (const e of edges) {
      const wire = wirePath(box(node(e.f), stage), box(node(e.t), stage));
      const n = Number(e.n) || 0;
      const path = document.createElementNS(NS, "path");
      path.setAttribute("class", e.col + (e.plain ? "" : !n ? " rest" : e.live ? " live" : ""));
      path.setAttribute("d", wire.d);
      path.style.strokeWidth = e.plain ? 1.5 : width(n);
      svg.appendChild(path);
      if (e.plain) continue;
      const label = document.createElementNS(NS, "text");
      label.setAttribute("x", wire.lx);
      label.setAttribute("y", wire.ly + 3.5);
      label.setAttribute("text-anchor", "middle");
      if (!n) label.setAttribute("class", "zero");
      label.textContent = e.n == null ? "—" : String(e.n);
      svg.appendChild(label);
    }
  }
  let raf = 0;
  const redraw = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(drawWires); };
  new ResizeObserver(redraw).observe($("stage"));

  async function loadPipeline() {
    const [overview, batch] = await Promise.allSettled([api("/api/overview"), api("/api/batch")]);
    state.overview = overview.status === "fulfilled" ? overview.value : null;
    state.batch = batch.status === "fulfilled" ? batch.value : null;
    const vault = state.overview?.vault;
    const errors = [
      overview.status === "rejected" && "概览：" + overview.reason.message,
      batch.status === "rejected" && "批处理：" + batch.reason.message,
      vault && !vault.ok && "笔记库：" + vault.error,
    ].filter(Boolean);
    $("rt-mode").innerHTML = errors.length ? `<span class="err">${esc(errors.join(" ｜ "))}</span>` : "";
    setText("n-drafts", state.batch ? pendingCount() : null);
    $("drafts-by").className = state.batch ? "" : "err";
    const waiting = projects().filter((p) => p.drafts).map((p) => `${p.project} ${p.drafts}`);
    setText("drafts-by", state.batch ? waiting.join(" · ") || "无待处理草稿" : "批处理状态不可用");
    setText("n-notes", vault?.ok ? vault.decisions + vault.lessons + vault.tips : null);
    setText("notes-by", vault?.ok ? `决策 ${vault.decisions} · 经验 ${vault.lessons} · 技巧 ${vault.tips}` : "原子笔记");
    setText("rt-cap", projects().map((p) => `${p.project}：待处理 ${p.drafts} · 已处理 ${p.processed}`).join(" ｜ ") || "还没有会话草稿");
    setText("version", state.overview ? "hinddian v" + state.overview.version : "");
    badges();
    redraw();
  }

  function draftItem(d) {
    const bits = [d.project, d.session_id ? "会话 " + d.session_id : "", d.jev_source ? "Jev " + d.jev_source : "", d.origin || ""].filter(Boolean);
    return `<button type="button" class="item" data-draft="${esc(d.id)}">
      <div class="t">${chip(d.status === "processed" ? "已处理" : "待处理", d.status === "processed" ? "ghost" : "decision")}<span>${esc(d.title || d.name)}</span></div>
      <span class="sc">${esc(when(d.mtime))}</span>
      <div class="s">${esc(bits.join(" · "))}${d.snippet ? " · " + esc(d.snippet) : ""}</div></button>`;
  }
  async function openDraft(id) {
    const sheet = $("sheet");
    $("sheet-kind").textContent = "草稿"; $("sheet-kind").className = "chip decision"; $("sheet-body").innerHTML = empty("加载中…");
    if (!sheet.open) sheet.showModal();
    try {
      const d = await api("/api/draft?id=" + encodeURIComponent(id));
      $("sheet-kind").textContent = d.status === "processed" ? "已处理草稿" : "待处理草稿";
      const meta = [d.project, d.session_id ? "会话 " + d.session_id : "", d.jev_source ? "Jev · " + d.jev_source : "", d.origin, when(d.mtime)].filter(Boolean).join(" · ");
      $("sheet-body").innerHTML = `<h3>${esc(d.title || d.name)}</h3>
        <div class="meta">${esc(meta)}</div><div class="meta"><code>${esc(d.id)}</code></div>
        <h4>正文</h4>${md(d.body || "") || empty("（空）")}`;
    } catch (e) { $("sheet-body").innerHTML = empty("打不开：" + e.message, true); }
  }
  $("sheet-close").addEventListener("click", () => $("sheet").close());
  $("sheet").addEventListener("click", (e) => { if (e.target === $("sheet")) $("sheet").close(); });
  for (const id of ["draft-list", "draft-processed"]) {
    $(id).addEventListener("click", (e) => { const b = e.target.closest("[data-draft]"); if (b) openDraft(b.dataset.draft); });
  }
  function renderDraftList(el, countEl, result, emptyMsg) {
    const rows = result.status === "fulfilled" ? result.value : null;
    setText(countEl, rows ? rows.length : null);
    $(el).innerHTML = rows ? rows.map(draftItem).join("") || empty(emptyMsg)
      : empty("读不到草稿：" + result.reason.message, true);
  }
  const SH = (ts) => ts ? new Date(ts * 1000).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }) + " (北京时间)" : "—";
  function jevItem(r) {
    const kind = r.keep === true ? chip("保留", "decision") : r.keep === false ? chip("丢弃", "ghost") : chip("未判", "ghost");
    const bits = [r.host, r.project || r.cwd, "来源 " + (r.jev_source || "none"), r.pushed ? "已写草稿" : "未写草稿", r.finalize_reason, r.outcome, r.turn_count != null ? r.turn_count + " 轮" : ""].filter(Boolean);
    return `<div class="item"><div class="t">${kind}<span>${esc(bits.join(" · "))}</span></div>
      <span class="sc">${esc(SH(r.ts))}</span>${r.error ? `<div class="s">错误：${esc(r.error)}</div>` : ""}</div>`;
  }
  async function loadJev() {
    try {
      const d = await api("/api/jev-decisions?limit=100"), s = d.summary || {};
      setText("jev-count", (d.items || []).length);
      const src = Object.entries(s.by_source_24h || {}).map(([k, v]) => `${k} ${v}`).join(" · ") || "无";
      const hosts = (s.hosts || []).map((h) => `${h.host}：最后 finalize ${SH(h.last_ts)}（24h ${h.count_24h} 次）`).join(" ｜ ");
      $("jev-summary").textContent = `近 24 小时 ${s.total_24h || 0} 次：保留 ${s.keep_24h || 0} · 丢弃 ${s.drop_24h || 0} · 写草稿 ${s.pushed_24h || 0}。来源：${src}。${hosts}`;
      $("jev-list").innerHTML = (d.items || []).length ? d.items.map(jevItem).join("") : empty("暂无 Jev 判断记录");
    } catch (e) { setText("jev-summary", ""); $("jev-list").innerHTML = empty("读不到 Jev 判断记录：" + e.message, true); setText("jev-count", null); }
  }
  async function loadDrafts() {
    const [batch, pending, processed] = await Promise.allSettled([
      api("/api/batch"), api("/api/drafts?status=pending&limit=100"), api("/api/drafts?status=processed&limit=30"), loadJev(),
    ]);
    renderDraftList("draft-list", "draft-list-count", pending, "没有待处理的会话草稿");
    renderDraftList("draft-processed", "draft-processed-count", processed, "还没有已处理的会话草稿");
    state.batch = batch.status === "fulfilled" ? batch.value : null;
    const rows = projects().slice().sort((a, b) => b.drafts - a.drafts);
    setText("batch-count", state.batch ? rows.length : null);
    $("batch").innerHTML = state.batch ? rows.map((p) => `<div class="batch-row">
      <b>${esc(p.project)}</b><span class="r">待 ${p.drafts} · 已 ${p.processed}</span></div>`).join("")
      || empty("还没有会话草稿") : empty("读不到批处理状态：" + batch.reason.message, true);
    badges();
  }

  function badges() {
    const count = state.batch ? pendingCount() : state.overview?.drafts.total || 0;
    const badge = $("badge-drafts");
    badge.hidden = !count; badge.textContent = count > 99 ? "99+" : count || "";
  }
  async function refresh(spin, withTab = true) {
    if (spin) $("refresh").classList.add("spin");
    const h = $("health");
    try {
      const result = await api("/api/health");
      h.className = "pill ok"; h.textContent = "● 在线 · v" + result.version;
    } catch { h.className = "pill bad"; h.textContent = "● 离线"; }
    if (withTab) await load(state.tab);
    $("refresh").classList.remove("spin");
  }
  $("refresh").addEventListener("click", () => refresh(true));
  window.addEventListener("hashchange", route);
  window.addEventListener("resize", redraw);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  setInterval(() => { if (!document.hidden && !$("sheet").open) refresh(); }, 60000);
  route();
  refresh(false, false);
})();
