/* hinddian dashboard — routing-style pipeline graph + grouped batch confirm */
(function () {
  const $ = (id) => document.getElementById(id);
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
  const setN = (id, v) => { $(id).textContent = v == null ? "—" : String(v); };
  function toast(msg, bad) {
    const t = $("toast"); t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 4000);
  }

  // ---------------- wires ----------------
  // Box of a node relative to the stage.
  function box(el, stage) {
    const r = el.getBoundingClientRect(), s = stage.getBoundingClientRect();
    const l = r.left - s.left, t = r.top - s.top;
    return { l, t, r: l + r.width, b: t + r.height, cx: l + r.width / 2, cy: t + r.height / 2 };
  }
  // Horizontal bezier when the target sits to the right, vertical otherwise (as Magpie's stage does).
  // t: where along the curve the count label sits (fan-outs label near the target).
  function wirePath(a, b, t = 0.5) {
    let p0, p1, p2, p3;
    if (b.l >= a.r - 2) {
      const mx = (a.r + b.l) / 2;
      [p0, p1, p2, p3] = [[a.r, a.cy], [mx, a.cy], [mx, b.cy], [b.l, b.cy]];
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

  function edges() {
    const s = state.stats, c = state.c || {}, h = c.hindsight || {};
    const reach = c.reachable !== false;
    return [
      { f: "inbox", t: "filter", n: s.inbox_count, col: "c-muted", live: s.inbox_count > 0 },
      { f: "filter", t: "quar", n: s.quarantine_count, col: "c-amber" },
      { f: "filter", t: "distill", n: (s.processed_count || 0) + (s.failed_count || 0), col: "c-accent" },
      { f: "filter", t: "retain", n: h.documents, col: "c-blue", todo: !c.hindsight_retain_enabled, label: c.hindsight_retain_enabled ? null : "未接" },
      { f: "distill", t: "pending", n: s.processed_count, col: "c-accent" },
      { f: "pending", t: "classify", n: reach ? c.pending_items : null, col: "c-accent", live: reach && c.pending_items > 0 && c.timer_active },
      { f: "classify", t: "o-auto", n: c.auto_applied, col: "c-green" },
      { f: "classify", t: "o-prop", n: c.proposals_pending, col: "c-amber" },
      { f: "classify", t: "o-ign", n: (c.ignored || 0) + (c.proposals_ignored_by_rule || 0), col: "c-muted" },
      { f: "classify", t: "o-fail", n: c.failed, col: "c-red" },
    ];
  }

  function drawWires() {
    const stage = $("stage"), svg = $("wires");
    svg.innerHTML = "";
    const node = (k) => stage.querySelector(`[data-n="${k}"]`);
    for (const e of edges()) {
      const a = node(e.f), b = node(e.t);
      if (!a || !b) continue;
      const fan = e.f === "filter" || e.f === "classify";
      const w = wirePath(box(a, stage), box(b, stage), fan ? 0.7 : 0.5);
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
  new ResizeObserver(redraw).observe($("stage"));
  window.addEventListener("resize", redraw);

  // ---------------- stage numbers ----------------
  function renderStage(filters) {
    const s = state.stats, c = state.c || {};
    setN("n-inbox", s.inbox_count || 0);
    setN("n-quar", s.quarantine_count || 0);
    setN("n-distill", s.processed_count || 0);
    setN("n-dfail", s.failed_count || 0);
    const box = $("filter-reasons");
    box.innerHTML = !filters || !filters.length
      ? `<div class="reason-row"><span class="note">暂无隔离原因</span></div>`
      : filters.map((r) => `<div class="reason-row"><code>${esc(r.reason)}</code><b>${esc(r.count)}</b></div>`).join("");

    const h = c.hindsight;
    if (!h) { setN("n-retain", null); $("retain-note").textContent = "未配置 key"; }
    else if (h.error) { setN("n-retain", "?"); $("retain-note").textContent = "不可达"; }
    else { setN("n-retain", h.documents); $("retain-note").textContent = c.hindsight_retain_enabled ? "worker 自动 retain" : "bank 文档 · 自动 retain 未接"; }

    if (c.reachable === false) {
      ["n-pending", "n-auto", "n-prop", "n-ign", "n-fail"].forEach((id) => setN(id, null));
      $("classify-chip").textContent = "DMIT 不可达";
      $("rt-cap").textContent = "DMIT 不可达：" + (c.error || "?");
    } else {
      setN("n-pending", c.pending_items);
      const byp = c.pending_by_project || {};
      $("pending-by").textContent = Object.keys(byp).map((k) => `${k} ${byp[k]}`).join(" · ") || "空";
      setN("n-auto", c.auto_applied);
      setN("n-prop", c.proposals_pending);
      setN("n-ign", (c.ignored || 0) + (c.proposals_ignored_by_rule || 0));
      $("ign-sub").textContent = `预过滤 ${c.prefiltered || 0} · 建议被规则忽略 ${c.proposals_ignored_by_rule || 0}`;
      setN("n-fail", c.failed);
      $("classify-model").textContent = (c.model || "pi").replace("magpie/", "");
      $("classify-chip").textContent = c.timer_active ? "每 15 分钟 · 5 条" : "定时已暂停";
      const lr = c.last_run;
      $("rt-cap").textContent = (lr ? `上次归类 ${fmtTime(lr.at)} · ${lr.count} 条` : "尚未运行") +
        ` · 已确认 ${c.proposals_applied || 0} · 已拒绝 ${c.proposals_rejected || 0}`;
    }
    $("rt-mode").textContent = `a 隔离 ${s.quarantine_count || 0} ｜ b 提炼 → 待入库 → pi 归类 ｜ c Hindsight retain${c.hindsight_retain_enabled ? "" : "（虚线：未接通）"}`;
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
    $("proposals-count").textContent = String(list.length);
    if (!list.length) { $("proposals-list").innerHTML = `<p class="empty">没有待确认的建议</p>`; updateSel(); return; }
    const groups = {};
    for (const p of list) (groups[p.target_path] = groups[p.target_path] || []).push(p);
    $("proposals-list").innerHTML = Object.keys(groups).sort().map((path) => {
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
    }).join("");
    updateSel();
  }
  function selectedIds() { return [...document.querySelectorAll("#proposals-list .prop .sel:checked")].map((c) => c.closest(".prop").dataset.id); }
  function updateSel() {
    const n = selectedIds().length;
    $("batchbar").hidden = n === 0;
    $("sel-count").textContent = `已选 ${n} 条`;
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
  $("proposals-list").addEventListener("change", (ev) => {
    if (ev.target.classList.contains("sel-all")) {
      ev.target.closest(".pgroup").querySelectorAll(".sel").forEach((c) => (c.checked = ev.target.checked));
    }
    updateSel();
  });
  $("proposals-list").addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    if (b.dataset.act) decide([b.closest(".prop").dataset.id], b.dataset.act);
    if (b.dataset.group) decide([...b.closest(".pgroup").querySelectorAll(".prop")].map((p) => p.dataset.id), b.dataset.group);
  });
  $("batchbar").addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-bulk]");
    if (b) decide(selectedIds(), b.dataset.bulk);
  });

  function renderIgnored(list) {
    $("ignored-count").textContent = list.length ? `（${list.length}）` : "";
    $("ignored-list").innerHTML = !list.length ? `<p class="note">无</p>` : list.map((p) => `<div class="row">
      <div><div class="title"><code>${esc(p.target_path)}</code> ${esc((p.patch_markdown || "").split("\n")[0].replace(/^#+\s*/, ""))}</div>
      <div class="meta">${esc(p.rule)} · ${esc(p.rule_reason || "")}</div></div>
      <button type="button" class="btn sm" data-restore="${esc(p.id)}">恢复</button></div>`).join("");
  }
  $("ignored-list").addEventListener("click", async (ev) => {
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
    $("recent-list").innerHTML = !rows.length ? `<p class="empty">暂无归类记录</p>` : rows.map((e) => {
      const [zh, cls] = EVENT_ZH[e.event] || [e.event, ""];
      const why = e.reason || e.error || e.summary || "";
      return `<div class="row"><div>
        <div class="title">${esc(e.title || e.source || e.proposal || "")} ${e.target ? `→ <code>${esc(e.target)}</code>` : ""}</div>
        <div class="meta">${fmtTime(e.at)}${why ? " · " + esc(why).slice(0, 160) : ""}</div></div>
        <span class="badge ${cls}">${esc(zh)}</span></div>`;
    }).join("");
  }
  function renderInbox(items) {
    $("inbox-count").textContent = String(items.length);
    $("inbox-list").innerHTML = !items.length ? `<p class="empty">收件箱为空</p>` : items.map((it) => `<div class="row">
      <div><div class="title">${esc(it.title || it.id)}</div>
      <div class="meta">${esc(it.project || "—")} · ${esc(it.source || "?")} · ${fmtTime(it.received_at)}</div></div>
      <span class="badge">${esc(it.bytes != null ? it.bytes + " B" : "")}</span></div>`).join("");
  }
  function renderTopics(topics) {
    $("topics-count").textContent = String(topics.length);
    $("topics-list").innerHTML = !topics.length ? `<p class="empty">无主题</p>` : topics.map((t) => `<div class="row">
      <div><div class="title">${esc(t.title)}</div><div class="meta"><code>${esc(t.document_id)}</code> · ${esc(t.vault_relpath)}</div></div>
      <span class="badge ${t.kind === "global" ? "ok" : ""}">${t.kind === "global" ? "全局 · 自动写入" : "项目 · 需确认"}</span></div>`).join("");
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
  async function refresh() {
    try {
      const health = await get("/api/health");
      $("health-pill").textContent = "在线 · v" + health.version; $("health-pill").className = "pill ok";
      $("demo-flag").textContent = health.demo ? "演示数据" : "";
    } catch { $("health-pill").textContent = "离线"; $("health-pill").className = "pill warn"; }
    const cp = refreshClassify();
    const [stats, inbox, filters, topics] = await Promise.all([get("/api/stats"), get("/api/inbox"), get("/api/filters"), get("/api/topics")]);
    state.stats = stats; state._filters = filters;
    renderStage(filters); renderInbox(inbox); renderTopics(topics);
    await cp;
  }

  $("btn-reasons").addEventListener("click", () => {
    const r = $("filter-reasons"); r.hidden = !r.hidden;
    $("btn-reasons").textContent = r.hidden ? "原因 ▾" : "原因 ▴";
  });
  $("btn-refresh").addEventListener("click", () => refresh().catch((e) => toast(e.message, true)));
  refresh().catch((e) => { console.error(e); toast("加载失败：" + e.message, true); });
  setInterval(() => refreshClassify().catch(() => {}), 60000);
})();
