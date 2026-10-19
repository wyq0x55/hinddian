/* hinddian dashboard — routing-style pipeline graph + grouped batch confirm */
(function () {
  const $ = (id) => document.getElementById(id);
  const setText = (id, v) => { const el = $(id); if (el) el.textContent = v == null ? "—" : String(v); };
  const setHtml = (id, html) => { const el = $(id); if (el) el.innerHTML = html; };
  const NS = "http://www.w3.org/2000/svg";
  const state = { stats: {}, c: {}, proposals: [] };

  async function get(path) {
    const res = await fetch(path, { headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error(path + " " + res.status);
    return res.json();
  }
  async function post(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Hinddian": "1" },
      body: JSON.stringify(body || {}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || res.status);
    return data;
  }
  const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const fmtTime = (iso) => { if (!iso) return "—"; try { return new Date(iso).toLocaleString("zh-CN", { hour12: false }); } catch { return iso; } };
  function toast(msg, bad) {
    const t = $("toast"); if (!t) return;
    t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 4000);
  }

  // ---------------- wires ----------------
  // Box of a node relative to the stage.
  function box(el, stage) {
    const r = el.getBoundingClientRect(), s = stage.getBoundingClientRect();
    const l = r.left - s.left, t = r.top - s.top;
    return { l, t, r: l + r.width, b: t + r.height, cx: l + r.width / 2, cy: t + r.height / 2 };
  }
  // Prefer vertical when the target is below (mobile fan-out), else horizontal to the right.
  // fan: stagger the exit point toward the target so analysis→技巧 exits cleanly, not sideways.
  // t: where along the curve the count label sits (fan-outs label near the target).
  function wirePath(a, b, t = 0.5, fan = false) {
    let p0, p1, p2, p3;
    // If target top is at/below source bottom, always drop vertically (even if also to the right).
    // This fixes mobile analysis→技巧 which sits down-right and used to take a sideways bezier.
    // Otherwise, if clearly to the right, exit the right side (desktop outs column).
    const below = b.t >= a.b - 4;
    const right = !below && b.l >= a.r - 2;
    if (below) {
      // Keep exit on the bottom edge, lightly nudged; clamp so it never hugs a corner.
      const raw = fan ? a.cx + (b.cx - a.cx) * 0.18 : a.cx;
      const exitX = Math.max(a.l + 10, Math.min(a.r - 10, raw));
      const my = a.b + Math.max(18, (b.t - a.b) * 0.55);
      [p0, p1, p2, p3] = [[exitX, a.b], [exitX, my], [b.cx, my], [b.cx, b.t]];
    } else if (right) {
      const rawY = fan ? a.cy + (b.cy - a.cy) * 0.25 : a.cy;
      const exitY = Math.max(a.t + 8, Math.min(a.b - 8, rawY));
      const mx = a.r + Math.max(16, (b.l - a.r) * 0.45);
      [p0, p1, p2, p3] = [[a.r, exitY], [mx, exitY], [mx, b.cy], [b.l, b.cy]];
    } else {
      const my = (a.b + b.t) / 2;
      [p0, p1, p2, p3] = [[a.cx, a.b], [a.cx, my], [b.cx, my], [b.cx, b.t]];
    }
    const u = 1 - t, k = [u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t];
    const lx = k[0] * p0[0] + k[1] * p1[0] + k[2] * p2[0] + k[3] * p3[0];
    const ly = k[0] * p0[1] + k[1] * p1[1] + k[2] * p2[1] + k[3] * p3[1];
    return { d: `M${p0[0]} ${p0[1]} C${p1[0]} ${p1[1]} ${p2[0]} ${p2[1]} ${p3[0]} ${p3[1]}`, lx, ly };
  }
  const width = (n) => (n > 0 ? Math.min(5, 1.4 + Math.log10(n + 1) * 1.3) : 1.2);

  function gsum(st, key = "drafts") { return ((state.g || {}).projects || []).filter((p) => !st || st.includes(p.state)).reduce((x, p) => x + (p[key] || 0), 0); }
  function edges() {
    const s = state.stats || {}, c = state.c || {}, os = c.obsidian_sync || {};
    const drafts = gsum(), ready = gsum(["ready", "accumulating"]), incr = gsum(["incremental"]), tips = gsum(["auto-tips"]);
    return [
      { f: "inbox", t: "filter", n: s.inbox_count, col: "c-muted", live: s.inbox_count > 0 },
      { f: "filter", t: "quar", n: s.quarantine_count, col: "c-amber" },
      { f: "filter", t: "drafts", n: s.processed_count, col: "c-accent" },
      { f: "drafts", t: "analysis", n: drafts, col: "c-accent", live: incr + tips > 0 },
      { f: "analysis", t: "o-batch", n: ready, col: "c-amber" },
      { f: "analysis", t: "o-incr", n: incr, col: "c-green" },
      { f: "analysis", t: "o-tips", n: tips, col: "c-blue" },
      { f: "o-batch", t: "obsidian", n: gsum(["ready", "accumulating"], "processed"), col: "c-amber" },
      { f: "o-incr", t: "obsidian", n: gsum(["incremental"], "processed"), col: "c-green" },
      { f: "o-tips", t: "obsidian", n: gsum(["auto-tips"], "processed"), col: "c-blue" },
      { f: "obsidian", t: "hindsight", n: os.synced, col: "c-blue", live: (os.pending || 0) > 0, label: os.notes ? `同步 ${os.synced}/${os.notes}` : "同步" },
    ];
  }

  function drawWires() {
    const stage = $("stage"), svg = $("wires");
    if (!stage || !svg) return;
    svg.innerHTML = "";
    const node = (k) => stage.querySelector(`[data-n="${k}"]`);
    for (const e of edges()) {
      const a = node(e.f), b = node(e.t);
      if (!a || !b) continue;
      const fan = e.f === "filter" || e.f === "analysis";
      const w = wirePath(box(a, stage), box(b, stage), fan ? 0.72 : 0.5, fan);
      const p = document.createElementNS(NS, "path");
      const n = Number(e.n) || 0;
      let cls = e.col;
      if (e.todo) cls += " todo";
      else if (!n) cls += " rest";
      else if (e.live) cls += " live";
      p.setAttribute("class", cls);
      p.setAttribute("d", w.d);
      p.style.strokeWidth = e.todo ? 1.5 : width(n);
      svg.appendChild(p);
      const txt = document.createElementNS(NS, "text");
      txt.setAttribute("x", w.lx); txt.setAttribute("y", w.ly + 3.5);
      txt.setAttribute("text-anchor", "middle");
      txt.setAttribute("class", n ? "" : "zero");
      txt.textContent = e.label ? `${e.label} · ${e.n ?? "—"}` : (e.n == null ? "—" : String(e.n));
      svg.appendChild(txt);
    }
  }
  let raf = 0;
  const redraw = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(drawWires); };
  const stageEl = $("stage"); if (stageEl) new ResizeObserver(redraw).observe(stageEl);
  window.addEventListener("resize", redraw);

  // ---------------- stage numbers ----------------
  function renderStage(filters) {
    const s = state.stats || {}, c = state.c || {}, g = state.g || {}, os = c.obsidian_sync, h = c.hindsight;
    setText("n-inbox", s.inbox_count || 0);
    setText("n-quar", s.quarantine_count || 0);
    // n-dfail is a sibling of drafts-by (not nested) so innerHTML updates cannot remove it
    setText("n-dfail", s.failed_count ? `失败 ${s.failed_count}` : "");
    const reasons = $("filter-reasons");
    if (reasons) {
      reasons.innerHTML = !filters || !filters.length
        ? `<div class="reason-row"><span class="note">暂无隔离原因</span></div>`
        : filters.map((r) => `<div class="reason-row"><code>${esc(r.reason)}</code><b>${esc(r.count)}</b></div>`).join("");
    }
    const ps = g.projects || [];
    setText("n-drafts", g.projects ? gsum() : null);
    setText("drafts-by", ps.filter((p) => p.drafts).map((p) => `${p.project} ${p.drafts}`).join(" · ") || "无积压");
    setText("n-batch", ps.filter((p) => p.state === "ready").length);
    setText("n-incr", gsum(["incremental"]));
    setText("n-tips", gsum(["auto-tips"]));
    setText("analysis-chip", c.timer_active === false ? "定时已暂停" : "每 15 分钟");
    setText("n-notes", os ? os.notes : null);
    if (os) { setText("n-hs", `${os.synced}/${os.notes}`); setText("hs-note", `${os.pending ? "同步中 · 剩 " + os.pending : "已全部同步"} · ${fmtTime(os.at)}`); }
    else { setText("n-hs", h && !h.error ? h.documents : null); setText("hs-note", "等待首次同步"); }
    const hold = Object.entries(g.holdout || {}).map(([k, v]) => `${k} ${v}`).join(" · ");
    setText("rt-mode", `Hindsight 只索引 Obsidian 笔记（document_id = 笔记 id）；原始会话不再直接 retain${hold ? " ｜ 保留集 " + hold : ""}`);
    setText("rt-cap", ps.map((p) => `${p.project}：${({ ready: "待批准", accumulating: "积累中", incremental: "增量", "auto-tips": "技巧" })[p.state] || p.state} · 已处理 ${p.processed}`).join(" ｜ ") || "—");
    redraw();
  }

  // ---------------- proposals (grouped) ----------------
  const ACTION_ZH = { append: "追加", merge: "改写一节", ignore: "忽略" };
  function diffHtml(diff) {
    if (!diff) return `<p class="note">无 diff</p>`;
    return `<pre class="diff">${diff.split("\n").map((l) => {
      const cls = l.startsWith("+++") || l.startsWith("---") ? "d-file" : l.startsWith("@@") ? "d-hunk" : l.startsWith("+") ? "d-add" : l.startsWith("-") ? "d-del" : "";
      return `<span class="${cls}">${esc(l)}</span>`;
    }).join("\n")}</pre>`;
  }
  function renderProposals(list) {
    state.proposals = list;
    setText("proposals-count", String(list.length));
    if (!list.length) { setHtml("proposals-list", `<p class="empty">没有待确认的建议</p>`); updateSel(); return; }
    const groups = {};
    for (const p of list) (groups[p.target_path] = groups[p.target_path] || []).push(p);
    setHtml("proposals-list", Object.keys(groups).sort().map((path) => {
      const ps = groups[path].sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
      const isNew = ps.some((p) => !p.target_exists) ? `<span class="badge info">新建</span>` : "";
      return `<div class="pgroup" data-path="${esc(path)}">
        <div class="pg-h">
          <input type="checkbox" class="sel-all" aria-label="全选此文件" />
          <code>${esc(path)}</code> ${isNew}<span class="count">${ps.length} 条</span><span class="grow"></span>
          <button type="button" class="btn sm ok" data-group="approve">全部确认</button>
          <button type="button" class="btn sm danger" data-group="reject">全部拒绝</button>
        </div>
        ${ps.map((p) => {
          const src = p.source || {};
          const head = (p.patch_markdown || "").trim().split("\n")[0].replace(/^#+\s*/, "");
          const flags = (p.flags || []).map((f) => `<span class="badge warn">${esc(f)}</span>`).join(" ");
          return `<div class="prop" data-id="${esc(p.id)}">
            <input type="checkbox" class="sel" aria-label="选择" />
            <div>
              <div class="head">${esc(head)} <span class="badge">${esc(ACTION_ZH[p.action] || p.action)}${p.section ? " · " + esc(p.section) : ""}</span> ${flags}</div>
              <div class="meta">来自 ${esc(src.title || src.relpath)} · 置信度 ${esc(p.confidence)} · ${fmtTime(p.created_at)}</div>
              <div class="reason">${esc(p.reason)}</div>
              <details><summary>查看 diff</summary>${diffHtml(p.diff)}</details>
              <div class="prop-actions">
                <button type="button" class="btn sm ok" data-act="approve">确认写入</button>
                <button type="button" class="btn sm danger" data-act="reject">拒绝</button>
              </div>
            </div>
          </div>`;
        }).join("")}
      </div>`;
    }).join(""));
    updateSel();
  }
  function selectedIds() { return [...document.querySelectorAll("#proposals-list .prop .sel:checked")].map((c) => c.closest(".prop").dataset.id); }
  function updateSel() {
    const n = selectedIds().length;
    const bar = $("batchbar"); if (bar) bar.hidden = n === 0;
    setText("sel-count", `已选 ${n} 条`);
  }
  async function decide(ids, act) {
    if (!ids.length) return;
    let reason = "";
    if (act === "approve") {
      if (!confirm(`确认把 ${ids.length} 条建议写入 Obsidian？同一文件会按顺序写入并自动续编号。`)) return;
    } else {
      const r = prompt(`拒绝 ${ids.length} 条，理由（可空）`, "");
      if (r === null) return;
      reason = r;
    }
    document.querySelectorAll("#proposals button").forEach((b) => (b.disabled = true));
    try {
      const res = ids.length === 1
        ? await post(`/api/classify/proposals/${encodeURIComponent(ids[0])}/${act}`, { reason })
        : await post(`/api/classify/proposals/batch`, { ids, action: act, reason });
      if (res.total != null) toast(`${act === "approve" ? "已写入" : "已拒绝"} ${res.done}/${res.total} 条` + (res.done < res.total ? "（部分失败，见记录）" : ""), res.done < res.total);
      else if (res.ok === false) throw new Error(res.error || "失败");
      else toast(act === "approve" ? `已写入 ${res.target_path || ""}` : "已拒绝");
    } catch (e) {
      toast("操作失败：" + e.message, true);
    }
    await refreshClassify();
  }
  $("proposals-list")?.addEventListener("change", (ev) => {
    if (ev.target.classList.contains("sel-all")) {
      ev.target.closest(".pgroup").querySelectorAll(".sel").forEach((c) => (c.checked = ev.target.checked));
    }
    updateSel();
  });
  $("proposals-list")?.addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    if (b.dataset.act) decide([b.closest(".prop").dataset.id], b.dataset.act);
    if (b.dataset.group) decide([...b.closest(".pgroup").querySelectorAll(".prop")].map((p) => p.dataset.id), b.dataset.group);
  });
  $("batchbar")?.addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-bulk]");
    if (b) decide(selectedIds(), b.dataset.bulk);
  });

  function renderIgnored(list) {
    setText("ignored-count", list.length ? `（${list.length}）` : "");
    setHtml("ignored-list", !list.length ? `<p class="note">无</p>` : list.map((p) => `<div class="row">
      <div><div class="title"><code>${esc(p.target_path)}</code> ${esc((p.patch_markdown || "").split("\n")[0].replace(/^#+\s*/, ""))}</div>
      <div class="meta">${esc(p.rule)} · ${esc(p.rule_reason || "")}</div></div>
      <button type="button" class="btn sm" data-restore="${esc(p.id)}">恢复</button></div>`).join(""));
  }
  $("ignored-list")?.addEventListener("click", async (ev) => {
    const b = ev.target.closest("button[data-restore]");
    if (!b) return;
    b.disabled = true;
    try { await post(`/api/classify/proposals/${encodeURIComponent(b.dataset.restore)}/restore`); toast("已恢复为待确认"); }
    catch (e) { toast("恢复失败：" + e.message, true); }
    await refreshClassify();
  });

  // ---------------- other lists ----------------
  const EVENT_ZH = {
    auto_applied: ["已写入", "ok"], proposal_created: ["生成建议", "warn"], proposal_applied: ["已确认写入", "ok"],
    proposal_rejected: ["已拒绝", "muted"], proposal_ignored_by_rule: ["规则忽略", "muted"], proposal_restored: ["已恢复", "info"],
    ignored: ["忽略", "muted"], failed: ["失败", "danger"],
  };
  function renderRecent(list) {
    const rows = (list || []).filter((e) => e.event !== "classified");
    setHtml("recent-list", !rows.length ? `<p class="empty">暂无归类记录</p>` : rows.map((e) => {
      const [zh, cls] = EVENT_ZH[e.event] || [e.event, ""];
      const why = e.reason || e.error || e.summary || "";
      return `<div class="row"><div>
        <div class="title">${esc(e.title || e.source || e.proposal || "")} ${e.target ? `→ <code>${esc(e.target)}</code>` : ""}</div>
        <div class="meta">${fmtTime(e.at)}${why ? " · " + esc(why).slice(0, 160) : ""}</div></div>
        <span class="badge ${cls}">${esc(zh)}</span></div>`;
    }).join(""));
  }
  function renderInbox(items) {
    setText("inbox-count", String(items.length));
    setHtml("inbox-list", !items.length ? `<p class="empty">收件箱为空</p>` : items.map((it) => `<div class="row">
      <div><div class="title">${esc(it.title || it.id)}</div>
      <div class="meta">${esc(it.project || "—")} · ${esc(it.source || "?")} · ${fmtTime(it.received_at)}</div></div>
      <span class="badge">${esc(it.bytes != null ? it.bytes + " B" : "")}</span></div>`).join(""));
  }
  function renderTopics(topics) {
    setText("topics-count", String(topics.length));
    setHtml("topics-list", !topics.length ? `<p class="empty">无主题</p>` : topics.map((t) => `<div class="row">
      <div><div class="title">${esc(t.title)}</div><div class="meta"><code>${esc(t.document_id)}</code> · ${esc(t.vault_relpath)}</div></div>
      <span class="badge ${t.kind === "global" ? "ok" : ""}">${t.kind === "global" ? "全局 · 自动写入" : "项目 · 需确认"}</span></div>`).join(""));
  }

  async function refreshClassify() {
    const [c, props, ign, recent] = await Promise.all([
      get("/api/classify/stats").catch((e) => ({ reachable: false, error: e.message })),
      get("/api/classify/proposals").catch(() => []),
      get("/api/classify/proposals?status=ignored_by_rule").catch(() => []),
      get("/api/classify/recent?limit=40").catch(() => []),
    ]);
    state.c = c;
    renderStage(state._filters);
    renderProposals(props);
    renderIgnored(ign);
    renderRecent(recent);
  }

  // ---------------- agent corrections (gated upsert) ----------------
  function renderCorrections(list) {
    const el = $("corrections-list"); if (!el) return;
    setText("corrections-count", String((list || []).length));
    if (!list || !list.length) {
      el.innerHTML = `<p class="empty">没有待确认的 Agent 修正</p>`;
      return;
    }
    el.innerHTML = list.map((c) => {
      const pl = c.payload || {};
      const head = esc(c.summary || pl.title || c.id);
      const meta = [
        esc(c.action || pl.action || ""),
        esc(c.type || pl.type || ""),
        c.project ? esc(c.project) : "",
        c.target_id ? `id=${esc(c.target_id)}` : "",
        fmtTime(c.created_at),
      ].filter(Boolean).join(" · ");
      const body = [pl.scene, pl.practice, pl.reason || c.reason].filter(Boolean).map((x) => esc(String(x).slice(0, 240))).join("<br/>");
      return `<div class="prop" data-cid="${esc(c.id)}">
        <div>
          <div class="head">${head} <span class="badge warn">Agent</span></div>
          <div class="meta">${meta}</div>
          <div class="reason">${body || esc(c.reason || "")}</div>
          <div class="prop-actions">
            <button type="button" class="btn sm ok" data-cact="approve">确认写入</button>
            <button type="button" class="btn sm danger" data-cact="reject">拒绝</button>
          </div>
        </div>
      </div>`;
    }).join("");
  }
  $("corrections-list")?.addEventListener("click", async (ev) => {
    const b = ev.target.closest("button[data-cact]");
    if (!b) return;
    const row = b.closest("[data-cid]");
    if (!row) return;
    const id = row.dataset.cid;
    const act = b.dataset.cact;
    let reason = "";
    if (act === "approve") {
      if (!confirm("确认把这条 Agent 修正写入 Obsidian？")) return;
    } else {
      const r = prompt("拒绝理由（可空）", "");
      if (r === null) return;
      reason = r;
    }
    b.disabled = true;
    try {
      await post(`/api/corrections/${encodeURIComponent(id)}/${act}`, { reason });
      toast(act === "approve" ? "已写入 Obsidian" : "已拒绝");
      await refreshCorrections();
    } catch (e) {
      toast("操作失败：" + e.message, true);
      b.disabled = false;
    }
  });
  async function refreshCorrections() {
    const list = await get("/api/corrections?status=pending").catch(() => []);
    renderCorrections(Array.isArray(list) ? list : []);
  }

    // ---------------- batch gate ----------------
  const GATE_ZH = { ready: "可批量分析", accumulating: "积累中", incremental: "增量自动", "auto-tips": "只抽技巧 · 自动" };
  function renderGate(g) {
    const el = $("gate-list"); if (!el) return;
    if (!g || !g.projects) { el.innerHTML = `<p class="empty">vault 主机 不可达</p>`; return; }
    const rows = g.projects.map((p) => `<div class="gate-row ${p.state}"><b>${esc(p.project)}</b>
      <span class="t">${esc(GATE_ZH[p.state] || p.state)}${p.running ? " · 运行中" : ""}</span>
      <span>会话草稿 ${p.drafts}${p.state === "accumulating" || p.state === "ready" ? " / " + p.threshold : ""} · 已处理 ${p.processed}</span>
      ${p.state === "ready" && !p.running ? `<button type="button" class="btn primary gate-go" data-p="${esc(p.project)}">开始批量分析</button>` : ""}</div>`);
    const hold = Object.entries(g.holdout || {}).map(([k, v]) => `${k} ${v}`).join(" · ");
    el.innerHTML = rows.join("") + (hold ? `<p class="note">增量测试保留集（不处理）：${esc(hold)}</p>` : "");
    setText("gate-count", g.projects.filter((p) => p.state === "ready").length + " 个待批准");
    el.querySelectorAll(".gate-go").forEach((b) => b.addEventListener("click", async () => {
      if (!confirm(`对「${b.dataset.p}」的全部会话草稿做一次批量分析？阈值按会话计（非每轮）。之后新会话草稿会自动增量合并。`)) return;
      b.disabled = true;
      try { await post(`/api/gate/${encodeURIComponent(b.dataset.p)}/approve`, {}); toast("已开始批量分析"); refreshGate(); }
      catch (e) { toast(e.message, true); b.disabled = false; }
    }));
  }
  async function refreshGate() { state.g = await get("/api/gate").catch(() => null); renderGate(state.g); renderStage(state._filters); }
  async function refresh() {
    try {
      const health = await get("/api/health");
      const pill = $("health-pill"); if (pill) { pill.textContent = "在线 · v" + health.version; pill.className = "pill ok"; }
      setText("demo-flag", health.demo ? "演示数据" : "");
    } catch { const pill = $("health-pill"); if (pill) { pill.textContent = "离线"; pill.className = "pill warn"; } }
    const cp = refreshClassify(); refreshGate(); refreshCorrections().catch(() => {});
    const [stats, inbox, filters, topics] = await Promise.all([get("/api/stats"), get("/api/inbox"), get("/api/filters"), get("/api/topics")]);
    state.stats = stats; state._filters = filters;
    renderStage(filters); renderInbox(inbox); renderTopics(topics);
    await cp;
  }

  $("btn-reasons")?.addEventListener("click", () => {
    const r = $("filter-reasons"); if (!r) return;
    r.hidden = !r.hidden;
    setText("btn-reasons", r.hidden ? "原因 ▾" : "原因 ▴");
  });
  $("btn-refresh")?.addEventListener("click", () => refresh().catch((e) => toast(e.message, true)));
  refresh().catch((e) => { console.error(e); toast("加载失败：" + e.message, true); });
  setInterval(() => { refreshClassify().catch(() => {}); refreshGate(); refreshCorrections().catch(() => {}); }, 60000);
})();
