/* hinddian dashboard — tabs: 流水线 / 待批准 / 笔记 / 草稿. No build step. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const TYPE_ZH = { decision: "决策", lesson: "经验", tip: "技巧", preference: "偏好" };
  const ACTION_ZH = { add: "新增", update: "修改", supersede: "取代", obsolete: "作废", create: "新增" };
  const STATE_ZH = { accumulating: ["积累中", "ghost"], ready: ["等你批准", "decision"], incremental: ["自动增量", "tip"], "auto-tips": ["只提技巧", "lesson"] };
  const FIELDS = [["scene", "场景"], ["practice", "做法"], ["reason", "理由"]];
  const TABS = ["pipeline", "review", "notes", "drafts"];
  const state = { tab: "pipeline", overview: null, gate: null, notes: [], type: "", project: "", q: "" };

  // ---------------- api ----------------
  async function api(path, opts = {}) {
    const init = { headers: { Accept: "application/json" }, ...opts };
    if (opts.body !== undefined) {
      init.method = opts.method || "POST";
      init.headers = { ...init.headers, "Content-Type": "application/json", "X-Hinddian": "1" };
      init.body = JSON.stringify(opts.body);
    }
    const res = await fetch(path, init);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `${res.status}`);
    return data;
  }
  function toast(msg, bad) {
    const t = $("toast");
    t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 3500);
  }
  const setText = (id, v) => { $(id).textContent = v == null ? "—" : v; };
  const empty = (msg, err) => `<p class="empty${err ? " err" : ""}">${esc(msg)}</p>`;
  const chip = (text, cls = "") => `<span class="chip ${esc(cls)}">${esc(text)}</span>`;
  const when = (iso) => { try { return new Date(iso).toLocaleString("zh-CN", { hour12: false, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }); } catch { return iso || ""; } };
  function md(text) {
    const lines = esc(text || "").replace(/`([^`]+)`/g, "<code>$1</code>").split("\n");
    let html = "", inList = false;
    for (const l of lines) {
      const m = l.match(/^\s*[-*]\s+(.*)$/);
      if (m) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${m[1]}</li>`; continue; }
      if (inList) { html += "</ul>"; inList = false; }
      if (l.trim()) html += `<p>${l}</p>`;
    }
    return html + (inList ? "</ul>" : "");
  }
  const projects = () => (state.gate || {}).projects || [];
  const gsum = (states, key = "drafts") => projects().filter((p) => !states || states.includes(p.state)).reduce((n, p) => n + (p[key] || 0), 0);

  // ---------------- routing ----------------
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
      else if (tab === "review") await loadReview();
      else if (tab === "notes") await loadNotes();
      else await loadGate();
    } catch (e) { toast(e.message, true); }
  }

  // ---------------- 流水线: wires ----------------
  function box(el, stage) {
    const r = el.getBoundingClientRect(), s = stage.getBoundingClientRect();
    const l = r.left - s.left, t = r.top - s.top;
    return { l, t, r: l + r.width, b: t + r.height, cx: l + r.width / 2, cy: t + r.height / 2 };
  }
  // Drop vertically when the target is below (phone layout), else exit right (desktop).
  // fan: nudge the exit toward the target so the analysis fork leaves cleanly; t: label position.
  function wirePath(a, b, t = 0.5, fan = false) {
    let p0, p1, p2, p3;
    const below = b.t >= a.b - 4, right = !below && b.l >= a.r - 2;
    if (below) {
      const raw = fan ? a.cx + (b.cx - a.cx) * 0.18 : a.cx;
      const x = Math.max(a.l + 10, Math.min(a.r - 10, raw)), my = a.b + Math.max(18, (b.t - a.b) * 0.55);
      [p0, p1, p2, p3] = [[x, a.b], [x, my], [b.cx, my], [b.cx, b.t]];
    } else if (right) {
      const raw = fan ? a.cy + (b.cy - a.cy) * 0.25 : a.cy;
      const y = Math.max(a.t + 8, Math.min(a.b - 8, raw)), mx = a.r + Math.max(16, (b.l - a.r) * 0.45);
      [p0, p1, p2, p3] = [[a.r, y], [mx, y], [mx, b.cy], [b.l, b.cy]];
    } else {
      const my = (a.b + b.t) / 2;
      [p0, p1, p2, p3] = [[a.cx, a.b], [a.cx, my], [b.cx, my], [b.cx, b.t]];
    }
    const u = 1 - t, k = [u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t];
    return { d: `M${p0} C${p1} ${p2} ${p3}`,
             lx: k[0] * p0[0] + k[1] * p1[0] + k[2] * p2[0] + k[3] * p3[0], ly: k[0] * p0[1] + k[1] * p1[1] + k[2] * p2[1] + k[3] * p3[1] };
  }
  const width = (n) => (n > 0 ? Math.min(5, 1.4 + Math.log10(n + 1) * 1.3) : 1.2);
  function edges() {
    const o = state.overview, d = o ? o.drafts : {}, s = (o && o.sync) || {};
    const ok = !!state.gate, pending = o ? o.corrections.pending : null;
    const n = (v) => (ok ? v : null);
    return [
      { f: "hooks", t: "jev", col: "c-muted", plain: true },
      { f: "jev", t: "drafts", n: d.ok ? d.total + d.processed : null, col: "c-accent" },
      { f: "drafts", t: "analysis", n: n(gsum()), col: "c-accent", live: gsum(["incremental", "auto-tips"]) > 0 },
      { f: "analysis", t: "o-batch", n: n(gsum(["ready", "accumulating"])), col: "c-amber", todo: projects().some((p) => p.state === "ready") },
      { f: "analysis", t: "o-incr", n: n(gsum(["incremental"])), col: "c-green", live: true },
      { f: "analysis", t: "o-tips", n: n(gsum(["auto-tips"])), col: "c-blue", live: true },
      { f: "o-batch", t: "obsidian", n: n(gsum(["ready", "accumulating"], "processed")), col: "c-amber" },
      { f: "o-incr", t: "obsidian", n: n(gsum(["incremental"], "processed")), col: "c-green" },
      { f: "o-tips", t: "obsidian", n: n(gsum(["auto-tips"], "processed")), col: "c-blue" },
      { f: "corr", t: "obsidian", n: pending, col: "c-amber", todo: pending > 0 },
      { f: "obsidian", t: "hindsight", n: s.notes != null ? s.synced ?? 0 : null, col: "c-blue", live: (s.pending || 0) > 0 },
    ];
  }
  function drawWires() {
    const stage = $("stage"), svg = $("wires");
    if (!stage.offsetParent) return; // hidden tab: nothing to measure
    svg.innerHTML = "";
    const node = (k) => stage.querySelector(`[data-n="${k}"]`);
    for (const e of edges()) {
      const a = node(e.f), b = node(e.t);
      if (!a || !b) continue;
      const fan = e.f === "analysis";
      const w = wirePath(box(a, stage), box(b, stage), fan ? 0.72 : 0.5, fan);
      const n = Number(e.n) || 0;
      const p = document.createElementNS(NS, "path");
      // live/todo only matter while something is actually waiting on that wire
      p.setAttribute("class", e.col + (e.plain ? "" : !n ? " rest" : e.todo ? " todo" : e.live ? " live" : ""));
      p.setAttribute("d", w.d);
      p.style.strokeWidth = e.plain || e.todo ? 1.5 : width(n);
      svg.appendChild(p);
      if (e.plain) continue;
      const txt = document.createElementNS(NS, "text");
      txt.setAttribute("x", w.lx); txt.setAttribute("y", w.ly + 3.5); txt.setAttribute("text-anchor", "middle");
      if (!n) txt.setAttribute("class", "zero");
      txt.textContent = e.n == null ? "—" : String(e.n);
      svg.appendChild(txt);
    }
  }
  let raf = 0;
  const redraw = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(drawWires); };
  new ResizeObserver(redraw).observe($("stage"));

  // ---------------- 流水线: numbers ----------------
  async function loadPipeline() {
    const [ov, gate] = await Promise.allSettled([api("/api/overview"), api("/api/gate")]);
    if (ov.status === "fulfilled") state.overview = ov.value;
    state.gate = gate.status === "fulfilled" ? gate.value : null;
    renderStage(ov.status === "rejected" ? ov.reason.message : null, gate.status === "rejected" ? gate.reason.message : null);
    badges();
  }
  function renderStage(ovErr, gateErr) {
    const o = state.overview, ps = projects();
    const v = o ? o.vault : {}, s = (o && o.sync) || {}, h = o && o.hindsight;
    const errs = [ovErr && "概览：" + ovErr, gateErr && "批处理：" + gateErr, o && !v.ok && "vault：" + v.error].filter(Boolean);
    $("rt-mode").innerHTML = errs.length ? `<span class="err">${esc(errs.join(" ｜ "))}</span>`
      : "Hindsight 只索引 Obsidian 笔记（document_id = 笔记 id）；Agent 读写都走 hinddian-memory";

    setText("n-drafts", state.gate ? gsum() : null);
    const by = $("drafts-by");
    by.className = state.gate ? "" : "err";
    by.textContent = state.gate ? ps.filter((p) => p.drafts).map((p) => `${p.project} ${p.drafts}`).join(" · ") || "无积压" : "批处理不可达";
    setText("analysis-chip", ps.some((p) => p.running) ? "分析中…" : "定时批处理");
    setText("n-batch", state.gate ? ps.filter((p) => p.state === "ready").length : null);
    setText("n-incr", state.gate ? gsum(["incremental"]) : null);
    setText("n-tips", state.gate ? gsum(["auto-tips"]) : null);

    setText("n-corr", o && o.corrections.ok ? o.corrections.pending : null);
    setText("n-notes", o && v.ok ? v.decisions + v.lessons + v.tips : null);
    const nb = $("notes-by");
    nb.className = o && !v.ok ? "err" : "";
    nb.textContent = !o ? "原子笔记 · 真相源" : v.ok ? `决策 ${v.decisions} · 经验 ${v.lessons} · 技巧 ${v.tips}` : "vault 不可达";
    const hs = $("hs-note");
    if (s.notes != null) {
      setText("n-hs", `${s.synced ?? 0}/${s.notes}`);
      const errN = (s.errors || []).length;
      hs.className = errN ? "err" : "";
      hs.textContent = `${s.pending ? "同步中 · 剩 " + s.pending : "已全部同步"}${errN ? ` · 出错 ${errN}` : ""}${s.at ? " · " + when(s.at) : ""}`;
    } else {
      setText("n-hs", h && !h.error ? h.documents : null);
      hs.className = h && h.error ? "err" : "";
      hs.textContent = h && h.error ? "Hindsight 不可达" : "等待首次同步";
    }
    setText("rt-cap", ps.map((p) => `${p.project}：${(STATE_ZH[p.state] || [p.state])[0]} · 已处理 ${p.processed}`).join(" ｜ ") || "还没有会话草稿");
    setText("version", o ? "hinddian v" + o.version : "");
    redraw();
  }

  // ---------------- 待批准 ----------------
  async function loadReview() {
    const [corr, gate] = await Promise.allSettled([api("/api/corrections"), api("/api/gate")]);
    if (corr.status === "rejected") { $("corrections").innerHTML = empty("读不到修正队列：" + corr.reason.message, true); setText("corr-count", null); }
    else await renderCorrections(corr.value);
    if (gate.status === "fulfilled") state.gate = gate.value;
    renderReady(gate.status === "rejected" ? gate.reason.message : null);
    badges();
  }
  async function renderCorrections(list) {
    setText("corr-count", list.length);
    if (!list.length) { $("corrections").innerHTML = empty("没有待批准的修正"); return; }
    const targets = await Promise.all(list.map((c) => c.target_id ? api("/api/note?id=" + encodeURIComponent(c.target_id)).catch(() => null) : null));
    $("corrections").innerHTML = list.map((c, i) => correctionCard(c, targets[i])).join("");
  }
  const noteLink = (id) => `<button type="button" class="btn link" data-note="${esc(id)}">${esc(id)}</button>`;
  function correctionCard(c, cur) {
    const p = c.payload || {};
    const claims = c.agent_claims || {};
    const fields = FIELDS.filter(([k]) => p[k]).map(([k, label]) => {
      const was = cur && cur[k] && cur[k] !== p[k] ? `<del>${esc(cur[k])}</del>` : "";
      return `<div><dt>${label}</dt><dd>${was}${esc(p[k])}</dd></div>`;
    }).join("");
    return `<article class="prop" data-cid="${esc(c.id)}">
      <div class="prop-h">${chip((ACTION_ZH[c.action] || c.action) + (TYPE_ZH[c.type] || c.type || ""), c.type)}
        ${c.project ? chip(c.project, "ghost") : ""}${p.origin === "batch-distill" ? chip("批处理增量", "ghost") : ""}${claims.user_confirmed ? chip("Agent 称用户已确认", "ghost") : ""}${claims.face_correction ? chip("当面纠错", "ghost") : ""}</div>
      <h3>${esc(c.summary || p.title || c.id)}</h3>
      <p class="meta">${esc(when(c.created_at))}${c.target_id ? " · 目标 " + noteLink(c.target_id) : ""}${(p.supersedes || []).length ? " · 取代 " + p.supersedes.map(noteLink).join(" ") : ""}</p>
      ${c.reason && c.reason !== p.reason ? `<p class="why">${p.origin === "batch-distill" ? "来源" : "Agent"}：${esc(c.reason)}</p>` : ""}
      ${fields ? `<dl class="diff">${fields}</dl>` : ""}
      <div class="acts">
        <button type="button" class="btn danger" data-act="reject">拒绝</button>
        <button type="button" class="btn ok" data-act="approve">批准写入</button>
      </div></article>`;
  }
  $("corrections").addEventListener("click", async (e) => {
    const noteBtn = e.target.closest("[data-note]");
    if (noteBtn) return openNote(noteBtn.dataset.note);
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const card = btn.closest("[data-cid]");
    const cid = card.dataset.cid, title = card.querySelector("h3").textContent;
    let body = {};
    if (btn.dataset.act === "approve") {
      if (!confirm(`批准并写入 Obsidian？\n\n「${title}」`)) return;
    } else {
      const reason = prompt(`拒绝「${title}」\n原因（可留空）：`, "");
      if (reason === null) return;
      body = { reason };
    }
    card.querySelectorAll("button").forEach((b) => (b.disabled = true));
    try {
      const r = await api(`/api/corrections/${encodeURIComponent(cid)}/${btn.dataset.act}`, { body });
      toast(btn.dataset.act === "approve" ? (r.ok ? "已写入" : "写入失败：" + JSON.stringify(r.result || r).slice(0, 80)) : "已拒绝", !r.ok);
      await refresh();
    } catch (err) { toast(err.message, true); card.querySelectorAll("button").forEach((b) => (b.disabled = false)); }
  });
  function renderReady(err) {
    if (err) { $("ready").innerHTML = empty("读不到批处理状态：" + err, true); setText("ready-count", null); return; }
    const ready = projects().filter((p) => p.state === "ready");
    setText("ready-count", ready.length);
    $("ready").innerHTML = ready.length ? ready.map((p) => `<div class="gate">
        <div class="p"><b>${esc(p.project)}</b>${chip(p.drafts + " 份草稿", "decision")}</div>
        <button type="button" class="btn ok" data-project="${esc(p.project)}" ${p.running ? "disabled" : ""}>${p.running ? "分析中…" : "开始"}</button>
        <div class="m">已攒够 ${esc(p.threshold)} 份，批准后做一次批量分析，之后自动增量</div>
      </div>`).join("") : empty("没有等待批准的项目");
  }
  $("ready").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-project]");
    if (!b || !confirm(`对「${b.dataset.project}」的全部会话草稿做一次批量分析？`)) return;
    b.disabled = true;
    try { await api(`/api/gate/${encodeURIComponent(b.dataset.project)}/approve`, { body: {} }); toast("已开始批量分析"); await refresh(); }
    catch (err) { toast(err.message, true); b.disabled = false; }
  });

  // ---------------- 笔记 ----------------
  async function loadNotes() {
    if (state.q) return search();
    const qs = new URLSearchParams({ limit: "300" });
    if (state.type) qs.set("type", state.type);
    if (state.project) qs.set("project", state.project);
    try {
      state.notes = await api("/api/notes?" + qs);
    } catch (e) { $("notes").innerHTML = empty("读不到笔记：" + e.message, true); return; }
    fillProjects(state.notes);
    $("notes-hint").textContent = `${state.notes.length} 条${state.type ? TYPE_ZH[state.type] : "笔记"}`;
    $("notes").innerHTML = state.notes.length ? state.notes.map((n) => noteItem(n.id, n.title, n.type, n.project)).join("") : empty("没有笔记");
  }
  function fillProjects(list) {
    const sel = $("project"), have = new Set([...sel.options].map((o) => o.value));
    [...new Set(list.map((n) => n.project).filter((p) => p && p !== "global"))].sort().forEach((p) => {
      if (!have.has(p)) sel.add(new Option(p, p));
    });
  }
  function noteItem(id, title, type, project, snippet, score) {
    const where = project && project !== "global" ? project : "";
    return `<button type="button" class="item" data-note="${esc(id)}">
      <div class="t">${chip(TYPE_ZH[type] || type || "笔记", type)}<span>${esc(title || id)}</span></div>${score != null ? `<span class="sc">${Number(score).toFixed(2)}</span>` : "<span></span>"}
      <div class="s">${esc([where, snippet].filter(Boolean).join(" · "))}</div></button>`;
  }
  async function search() {
    $("notes").innerHTML = empty("检索中…");
    let r;
    try { r = await api("/api/recall", { body: { query: state.q, project: state.project } }); }
    catch (e) { $("notes").innerHTML = empty("检索失败：" + e.message, true); return; }
    let rows = (r.results || []).map((x) => {
      const meta = x.metadata || {}, sc = x.scores || {};
      const text = (x.text || x.practice || x.scene || "").replace(/^---[\s\S]*?\n---\n/, "").replace(/^#.*$/gm, "").replace(/^\s*[-*]\s+/gm, "").replace(/\s+/g, " ").trim();
      return { id: x.document_id || x.id, title: meta.title || x.title, type: meta.type || x.type, project: meta.project || x.project,
               snippet: text.slice(0, 140), score: sc.reranker ?? sc.final ?? x.score };
    });
    if (state.type) rows = rows.filter((x) => x.type === state.type);
    $("notes-hint").textContent = r.via === "hindsight" ? `Hindsight 检索 · ${rows.length} 条` : `Hindsight 不可用，本地检索 · ${rows.length} 条`;
    $("notes").innerHTML = rows.length ? rows.map((x) => noteItem(x.id, x.title, x.type, x.project, x.snippet, x.score)).join("") : empty("没有相关记忆");
  }
  $("search").addEventListener("submit", (e) => { e.preventDefault(); state.q = $("q").value.trim(); $("q").blur(); loadNotes(); });
  $("q").addEventListener("input", () => { if (!$("q").value.trim() && state.q) { state.q = ""; loadNotes(); } });
  $("type-seg").addEventListener("click", (e) => {
    const b = e.target.closest("[data-type]");
    if (!b) return;
    state.type = b.dataset.type;
    $("type-seg").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    loadNotes();
  });
  $("project").addEventListener("change", () => { state.project = $("project").value; loadNotes(); });
  $("notes").addEventListener("click", (e) => { const b = e.target.closest("[data-note]"); if (b) openNote(b.dataset.note); });

  async function openNote(id) {
    const sheet = $("sheet");
    $("sheet-kind").textContent = "笔记"; $("sheet-kind").className = "chip"; $("sheet-body").innerHTML = empty("加载中…");
    if (!sheet.open) sheet.showModal();
    try {
      const n = await api("/api/note?id=" + encodeURIComponent(id));
      $("sheet-kind").textContent = TYPE_ZH[n.type] || n.type || "笔记";
      $("sheet-kind").className = "chip " + (n.type || "");
      const links = (ids, label) => ids && ids.length ? `<h4>${label}</h4><div class="rel">${ids.map(noteLink).join("")}</div>` : "";
      $("sheet-body").innerHTML = `<h3>${esc(n.title)}</h3>
        <div class="meta">${esc(n.project && n.project !== "global" ? n.project + " · " : "")}${n.status !== "active" ? esc(n.status) + " · " : ""}更新于 ${esc(n.updated || "—")}</div>
        <div class="meta"><code>${esc(n.id)}</code></div>
        ${FIELDS.map(([k, label]) => n[k] ? `<h4>${label}</h4>${md(n[k])}` : "").join("")}
        ${n.superseded_by ? links([n.superseded_by], "已被取代为") : ""}${links(n.supersedes, "取代了")}${links(n.related, "相关")}
        <h4>文件</h4><p class="meta"><code>${esc(n.path)}.md</code></p>`;
    } catch (e) { $("sheet-body").innerHTML = empty("打不开：" + e.message, true); }
  }
  $("sheet-close").addEventListener("click", () => $("sheet").close());
  $("sheet").addEventListener("click", (e) => { if (e.target === $("sheet")) $("sheet").close(); const b = e.target.closest("[data-note]"); if (b) openNote(b.dataset.note); });

  // ---------------- 草稿 ----------------
  async function loadGate() {
    try { state.gate = await api("/api/gate"); }
    catch (e) { $("gate").innerHTML = empty("读不到批处理状态：" + e.message, true); setText("gate-count", null); return; }
    const ps = projects().slice().sort((a, b) => (b.state === "ready") - (a.state === "ready") || b.drafts - a.drafts);
    setText("gate-count", ps.length);
    $("gate").innerHTML = ps.length ? ps.map((p) => {
      const [label, cls] = STATE_ZH[p.state] || [p.state, ""];
      const acc = p.state === "accumulating" || p.state === "ready";
      const pct = Math.min(100, Math.round((p.drafts / (p.threshold || 1)) * 100));
      return `<div class="gate">
        <div class="p"><b>${esc(p.project)}</b>${chip(p.running ? "分析中…" : label, cls)}</div>
        <span class="r">${acc ? `${esc(p.drafts)} / ${esc(p.threshold)}` : `待 ${esc(p.drafts)} · 已 ${esc(p.processed)}`}</span>
        ${acc ? `<div class="bar${pct >= 100 ? " full" : ""}"><i style="width:${pct}%"></i></div>` : ""}
        ${p.approved_at ? `<div class="m">批准于 ${esc(when(p.approved_at))}</div>` : ""}
      </div>`;
    }).join("") : empty("还没有会话草稿");
    badges();
  }

  // ---------------- chrome ----------------
  function badges() {
    const o = state.overview;
    const pending = o ? o.corrections.pending + o.drafts.ready : null;
    const b = $("badge-review");
    b.hidden = !pending; b.textContent = pending || "";
    const drafts = state.gate ? gsum() : o && o.drafts.ok ? o.drafts.total : 0;
    const d = $("badge-drafts");
    d.hidden = !drafts; d.textContent = drafts > 99 ? "99+" : drafts || "";
  }
  async function refresh(spin, withTab = true) {
    if (spin) $("refresh").classList.add("spin");
    const h = $("health");
    try {
      const r = await api("/api/health");
      h.className = "pill ok"; h.textContent = "● 在线 · v" + r.version;
    } catch { h.className = "pill bad"; h.textContent = "● 离线"; }
    try { if (state.tab !== "pipeline") state.overview = await api("/api/overview"); } catch { /* badges stay as they were */ }
    if (withTab) await load(state.tab);
    else badges();
    $("refresh").classList.remove("spin");
  }
  $("refresh").addEventListener("click", () => refresh(true));
  window.addEventListener("hashchange", route);
  window.addEventListener("resize", redraw);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  setInterval(() => { if (!document.hidden && !$("sheet").open) refresh(); }, 60000);
  route();               // loads the current tab
  refresh(false, false); // health + badges only
})();
