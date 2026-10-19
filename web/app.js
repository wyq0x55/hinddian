/* hinddian dashboard — tabs: 待批准 / 笔记 / 草稿 / 概览. No build step. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const TYPE_ZH = { decision: "决策", lesson: "经验", tip: "技巧", preference: "偏好" };
  const ACTION_ZH = { add: "新增", update: "修改", supersede: "取代", obsolete: "作废", create: "新增" };
  const STATE_ZH = { accumulating: ["积累中", ""], ready: ["等你批准", "decision"], incremental: ["自动增量", "tip"], "auto-tips": ["只提技巧 · 自动", "lesson"] };
  const FIELDS = [["scene", "场景"], ["practice", "做法"], ["reason", "理由"]];
  const TABS = ["review", "notes", "drafts", "overview"];
  const state = { tab: "review", overview: null, gate: null, notes: [], type: "", project: "", q: "" };

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

  // ---------------- routing ----------------
  function route() {
    const tab = (location.hash || "#review").slice(1);
    state.tab = TABS.includes(tab) ? tab : "review";
    for (const t of TABS) $("view-" + t).hidden = t !== state.tab;
    document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === state.tab));
    load(state.tab);
  }
  async function load(tab) {
    try {
      if (tab === "review") await loadReview();
      else if (tab === "notes") await loadNotes();
      else if (tab === "drafts") await loadGate();
      else await loadOverview();
    } catch (e) { toast(e.message, true); }
  }

  // ---------------- 待批准 ----------------
  async function loadReview() {
    const [corr, gate] = await Promise.allSettled([api("/api/corrections"), api("/api/gate")]);
    if (corr.status === "rejected") $("corrections").innerHTML = empty("读不到修正队列：" + corr.reason.message, true);
    else await renderCorrections(corr.value);
    if (gate.status === "fulfilled") state.gate = gate.value;
    renderReady(gate.status === "rejected" ? gate.reason.message : null);
    badges();
  }
  async function renderCorrections(list) {
    if (!list.length) { $("corrections").innerHTML = empty("没有待批准的修正"); return; }
    const targets = await Promise.all(list.map((c) => c.target_id ? api("/api/note?id=" + encodeURIComponent(c.target_id)).catch(() => null) : null));
    $("corrections").innerHTML = list.map((c, i) => correctionCard(c, targets[i])).join("");
  }
  function correctionCard(c, cur) {
    const p = c.payload || {};
    const claims = c.agent_claims || {};
    const fields = FIELDS.filter(([k]) => p[k]).map(([k, label]) => {
      const was = cur && cur[k] && cur[k] !== p[k] ? `<span class="was">${esc(cur[k])}</span>` : "";
      return `<div class="field"><dt>${label}</dt><dd>${esc(p[k])}${was}</dd></div>`;
    }).join("");
    return `<article class="card" data-cid="${esc(c.id)}">
      <div class="card-top">${chip(ACTION_ZH[c.action] || c.action)}${chip(TYPE_ZH[c.type] || c.type || "?", c.type)}
        ${c.project ? chip(c.project) : ""}${claims.user_confirmed ? chip("Agent 称用户已确认", "claim") : ""}${claims.face_correction ? chip("当面纠错", "claim") : ""}</div>
      <h3>${esc(c.summary || p.title || c.id)}</h3>
      <div class="meta">${esc(when(c.created_at))}${c.target_id ? ` · 目标 <button type="button" class="btn link" data-note="${esc(c.target_id)}">${esc(c.target_id)}</button>` : ""}</div>
      ${(p.supersedes || []).length ? `<div class="meta">取代 ${p.supersedes.map((id) => `<button type="button" class="btn link" data-note="${esc(id)}">${esc(id)}</button>`).join(" ")}</div>` : ""}
      ${c.reason && c.reason !== p.reason ? `<p class="meta">修正原因：${esc(c.reason)}</p>` : ""}
      ${fields ? `<dl class="fields">${fields}</dl>` : ""}
      <div class="actions">
        <button type="button" class="btn danger" data-act="reject">拒绝</button>
        <button type="button" class="btn primary" data-act="approve">批准写入</button>
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
      await loadReview();
    } catch (err) { toast(err.message, true); card.querySelectorAll("button").forEach((b) => (b.disabled = false)); }
  });
  function renderReady(err) {
    if (err) { $("ready").innerHTML = empty("读不到批处理状态：" + err, true); return; }
    const ready = ((state.gate || {}).projects || []).filter((p) => p.state === "ready");
    $("ready").innerHTML = ready.length ? ready.map((p) => `<article class="card">
        <div class="row-2"><h3>${esc(p.project)}</h3>${chip(p.drafts + " 份草稿", "decision")}</div>
        <p class="meta">已攒够 ${esc(p.threshold)} 份会话草稿，批准后做一次批量分析，之后自动增量。</p>
        <div class="actions"><span></span><button type="button" class="btn primary" data-project="${esc(p.project)}" ${p.running ? "disabled" : ""}>${p.running ? "分析中…" : "开始批量分析"}</button></div>
      </article>`).join("") : empty("没有等待批准的项目");
  }
  $("ready").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-project]");
    if (!b || !confirm(`对「${b.dataset.project}」的全部会话草稿做一次批量分析？`)) return;
    b.disabled = true;
    try { await api(`/api/gate/${encodeURIComponent(b.dataset.project)}/approve`, { body: {} }); toast("已开始批量分析"); await loadReview(); }
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
    return `<button type="button" class="item" data-note="${esc(id)}">
      <div class="t">${chip(TYPE_ZH[type] || type || "笔记", type)}<span>${esc(title || id)}</span>${score != null ? `<span class="score">${Number(score).toFixed(2)}</span>` : ""}</div>
      <div class="s">${esc(snippet || (project && project !== "global" ? project : ""))}</div></button>`;
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
    $("sheet-kind").textContent = "笔记"; $("sheet-body").innerHTML = empty("加载中…");
    if (!sheet.open) sheet.showModal();
    try {
      const n = await api("/api/note?id=" + encodeURIComponent(id));
      $("sheet-kind").textContent = TYPE_ZH[n.type] || n.type || "笔记";
      $("sheet-kind").className = "chip " + (n.type || "");
      const links = (ids, label) => ids && ids.length ? `<h4>${label}</h4><div class="rel">${ids.map((r) => `<button type="button" class="btn link" data-note="${esc(r)}">${esc(r)}</button>`).join("")}</div>` : "";
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
    catch (e) { $("gate").innerHTML = empty("读不到批处理状态：" + e.message, true); return; }
    const ps = (state.gate.projects || []).slice().sort((a, b) => (b.state === "ready") - (a.state === "ready") || b.drafts - a.drafts);
    $("gate").innerHTML = ps.length ? ps.map((p) => {
      const [label, cls] = STATE_ZH[p.state] || [p.state, ""];
      const pct = p.state === "accumulating" ? Math.min(100, Math.round((p.drafts / (p.threshold || 1)) * 100)) : 100;
      return `<article class="card">
        <div class="row-2"><h3>${esc(p.project)}</h3>${chip(p.running ? "分析中…" : label, cls)}</div>
        ${p.state === "accumulating" ? `<div class="bar"><i style="width:${pct}%"></i></div>` : ""}
        <div class="meta">待处理 ${esc(p.drafts)}${p.state === "accumulating" ? ` / ${esc(p.threshold)}` : ""} 份 · 已合并 ${esc(p.processed)} 份${p.approved_at ? " · 批准于 " + esc(when(p.approved_at)) : ""}</div>
      </article>`;
    }).join("") : empty("还没有会话草稿");
    badges();
  }

  // ---------------- 概览 ----------------
  async function loadOverview() {
    state.overview = await api("/api/overview");
    const o = state.overview, v = o.vault, d = o.drafts, s = o.sync || {}, h = o.hindsight;
    const kpi = (label, n, sub) => `<div class="kpi"><span>${esc(label)}</span><b>${esc(n)}</b>${sub ? `<small>${esc(sub)}</small>` : ""}</div>`;
    $("kpis").innerHTML = [
      kpi("原子笔记", v.ok ? v.decisions + v.lessons + v.tips : "—", v.ok ? `决策 ${v.decisions} · 经验 ${v.lessons} · 技巧 ${v.tips}` : "vault 不可达"),
      kpi("待批准", o.corrections.pending + d.ready, `修正 ${o.corrections.pending} · 项目 ${d.ready}`),
      kpi("草稿积压", d.ok ? d.total : "—", d.ok ? `已合并 ${d.processed}` : "批处理不可达"),
      kpi("Hindsight 索引", s.notes != null ? `${s.synced ?? 0}/${s.notes}` : "—", s.at ? "同步于 " + when(s.at) : "尚未同步"),
    ].join("");
    const step = (dot, title, n, sub) => `<li><span class="dot ${dot}"></span><div><b>${esc(title)}</b><small>${esc(sub)}</small></div><span class="n">${esc(n)}</span></li>`;
    $("flow").innerHTML = [
      step("ok", "会话 hooks", "", "每轮缓冲；会话结束 → Jev 判断值不值得记"),
      step(d.ok ? (d.total ? "warn" : "ok") : "bad", "会话草稿", d.ok ? d.total : "!", d.ok ? "按项目攒；新项目满阈值后等你批准" : d.error || "不可达"),
      step(d.ok ? "ok" : "bad", "批处理", d.ok ? d.processed : "!", "草稿 → 原子笔记（决策 / 经验 / 技巧）"),
      step(v.ok ? "ok" : "bad", "Obsidian（真相源）", v.ok ? v.decisions + v.lessons + v.tips : "!", v.ok ? `${v.projects} 个项目` : v.error || "不可达"),
      step(s.notes != null ? ((s.pending || (s.errors || []).length) ? "warn" : "ok") : "", "Hindsight 索引", s.notes != null ? s.synced ?? 0 : "—",
           h && h.error ? "Hindsight 不可达" : s.notes != null ? `待同步 ${s.pending || 0}${(s.errors || []).length ? ` · 出错 ${s.errors.length}` : ""}` : "定时同步，Agent 只读"),
    ].join("");
    $("version").textContent = "hinddian v" + o.version;
    badges();
  }

  // ---------------- chrome ----------------
  function badges() {
    const o = state.overview;
    const pending = o ? o.corrections.pending + o.drafts.ready : null;
    const b = $("badge-review");
    b.hidden = !pending; b.textContent = pending || "";
    const ready = ((state.gate || {}).projects || []).reduce((n, p) => n + (p.drafts || 0), 0);
    const d = $("badge-drafts");
    d.hidden = !ready; d.textContent = ready > 99 ? "99+" : ready || "";
  }
  async function refresh(spin, withTab = true) {
    if (spin) $("refresh").classList.add("spin");
    try {
      const h = await api("/api/health");
      $("health").className = "health ok"; $("health").title = "在线 · v" + h.version;
    } catch { $("health").className = "health bad"; $("health").title = "离线"; }
    try { if (state.tab !== "overview") state.overview = await api("/api/overview"); } catch { /* badges stay as they were */ }
    if (withTab) await load(state.tab);
    else badges();
    $("refresh").classList.remove("spin");
  }
  $("refresh").addEventListener("click", () => refresh(true));
  window.addEventListener("hashchange", route);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  setInterval(() => { if (!document.hidden && !$("sheet").open) refresh(); }, 60000);
  route();               // loads the current tab
  refresh(false, false); // health + badges only
})();
