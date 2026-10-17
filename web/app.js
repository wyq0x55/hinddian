/* hinddian dashboard — Magpie-like branched pipeline UI */
(function () {
  const $ = (id) => document.getElementById(id);

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
  function esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function fmtTime(iso) {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString("zh-CN", { hour12: false }); } catch { return iso; }
  }
  function num(el, n) { el.textContent = n == null ? "—" : String(n); }
  function toast(msg, bad) {
    const t = $("toast");
    t.textContent = msg;
    t.className = "toast" + (bad ? " bad" : "");
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (t.hidden = true), 3500);
  }

  function renderPipeline(s, filters) {
    num($("pipe-inbox"), s.inbox_count || 0);
    const q = s.quarantine_count || 0;
    $("pipe-quarantine").textContent = String(q);
    num($("pipe-processed"), s.processed_count || 0);
    num($("pipe-failed"), s.failed_count || 0);

    const demoPill = $("demo-pill");
    demoPill.textContent = s.demo ? "demo" : "真实数据";
    demoPill.className = "pill " + (s.demo ? "demo" : "live");
    $("demo-flag").textContent = s.demo ? "演示数据 · USE_DEMO_DATA" : "";

    const box = $("filter-reasons");
    box.innerHTML = !filters || !filters.length
      ? `<div class="reason-row"><span class="empty" style="padding:8px 0">暂无隔离原因</span></div>`
      : filters.map((r) => `<div class="reason-row"><code>${esc(r.reason)}</code><span class="reason-n">${esc(r.count)}</span></div>`).join("");
  }

  function renderClassify(c) {
    if (!c || c.reachable === false) {
      ["pipe-pending-items", "pipe-auto", "pipe-proposals", "pipe-decided", "pipe-ignored", "pipe-cfailed"].forEach((id) => num($(id), null));
      $("classify-last").textContent = "DMIT 不可达：" + ((c && c.error) || "?");
    } else {
      num($("pipe-pending-items"), c.pending_items);
      const byp = c.pending_by_project || {};
      $("pending-by-project").textContent = Object.keys(byp).map((k) => `${k} ${byp[k]}`).join(" · ") || "空";
      num($("pipe-auto"), c.auto_applied);
      num($("pipe-proposals"), c.proposals_pending);
      $("pipe-decided").textContent = `${c.proposals_applied || 0} / ${c.proposals_rejected || 0}`;
      num($("pipe-ignored"), c.ignored);
      num($("pipe-cfailed"), c.failed);
      $("classify-model").textContent = "DMIT · " + (c.model || "pi") + " · 每 15 分钟 5 条";
      const lr = c.last_run;
      $("classify-last").textContent = lr ? `上次运行 ${fmtTime(lr.at)} · ${lr.count} 条` : "尚未定时运行";
    }
    const h = c && c.hindsight;
    const hEl = $("pipe-hindsight");
    if (!h) { hEl.textContent = "—"; $("hindsight-note").textContent = "未配置 Hindsight key"; }
    else if (h.error) { hEl.textContent = "?"; $("hindsight-note").textContent = "Hindsight 不可达"; }
    else {
      hEl.textContent = String(h.documents);
      $("hindsight-note").textContent =
        (c.hindsight_retain_enabled ? "worker 过滤后自动 retain" : "⚠ worker 尚未自动 retain（待接）") +
        ` · 待处理 ${h.pending_operations} · 失败 ${h.failed_operations}`;
    }
  }

  function diffHtml(diff) {
    if (!diff) return `<p class="empty">无 diff</p>`;
    return `<pre class="diff">${diff.split("\n").map((l) => {
      let cls = "";
      if (l.startsWith("+++") || l.startsWith("---")) cls = "d-file";
      else if (l.startsWith("@@")) cls = "d-hunk";
      else if (l.startsWith("+")) cls = "d-add";
      else if (l.startsWith("-")) cls = "d-del";
      return `<span class="${cls}">${esc(l)}</span>`;
    }).join("\n")}</pre>`;
  }

  const ACTION_ZH = { append: "追加", merge: "合并改写", ignore: "忽略" };

  function renderProposals(list) {
    $("proposals-count").textContent = String(list.length);
    if (!list.length) { $("proposals-list").innerHTML = `<p class="empty">没有待确认的建议</p>`; return; }
    $("proposals-list").innerHTML = list.map((p) => {
      const src = p.source || {};
      const flags = (p.flags || []).map((f) => `<span class="badge warn">${esc(f)}</span>`).join(" ");
      const isNew = p.target_exists ? "" : `<span class="badge info">新建</span>`;
      return `<div class="prop" data-id="${esc(p.id)}">
        <div class="prop-h">
          <div>
            <div class="title"><code>${esc(p.target_path)}</code> ${isNew} <span class="badge">${esc(ACTION_ZH[p.action] || p.action)}${p.section ? " · " + esc(p.section) : ""}</span> ${flags}</div>
            <div class="meta">来自：${esc(src.title || src.relpath)} · 置信度 ${esc(p.confidence)} · ${fmtTime(p.created_at)}</div>
            <div class="reason">${esc(p.reason)}</div>
          </div>
        </div>
        <details><summary>查看 diff</summary>${diffHtml(p.diff)}</details>
        <div class="prop-actions">
          <button type="button" class="btn ok" data-act="approve">确认写入</button>
          <button type="button" class="btn danger" data-act="reject">拒绝</button>
        </div>
      </div>`;
    }).join("");
  }

  const EVENT_ZH = {
    auto_applied: ["已写入", "ok"], proposal_created: ["生成建议", "warn"], proposal_applied: ["已确认写入", "ok"],
    proposal_rejected: ["已拒绝", "muted"], ignored: ["忽略", "muted"], failed: ["失败", "danger"], classified: ["已归类", "info"],
  };

  function renderRecent(list) {
    const rows = (list || []).filter((e) => e.event !== "classified");
    if (!rows.length) { $("recent-list").innerHTML = `<p class="empty">暂无归类记录</p>`; return; }
    $("recent-list").innerHTML = rows.map((e) => {
      const [zh, cls] = EVENT_ZH[e.event] || [e.event, ""];
      const what = e.target ? `→ <code>${esc(e.target)}</code>` : "";
      const why = e.reason || e.error || e.summary || "";
      return `<div class="row">
        <div>
          <div class="title">${esc(e.title || e.source || e.proposal || "")} ${what}</div>
          <div class="meta">${fmtTime(e.at)}${why ? " · " + esc(why).slice(0, 160) : ""}</div>
        </div>
        <span class="badge ${cls}">${esc(zh)}</span>
      </div>`;
    }).join("");
  }

  function renderInbox(items) {
    $("inbox-count").textContent = String(items.length);
    $("inbox-list").innerHTML = !items.length ? `<p class="empty">收件箱为空</p>` : items.map((it) => `<div class="row">
        <div><div class="title">${esc(it.title || it.id)}</div>
        <div class="meta">${esc(it.project || "—")} · ${esc(it.source || "?")} · ${esc(it.agent || "")} · ${fmtTime(it.received_at)}</div></div>
        <span class="badge">${esc(it.bytes != null ? it.bytes + " B" : "")}</span></div>`).join("");
  }

  function renderTopics(topics) {
    $("topics-count").textContent = String(topics.length);
    $("topics-list").innerHTML = !topics.length ? `<p class="empty">无主题</p>` : topics.map((t) => `<div class="row">
        <div><div class="title">${esc(t.title)} <span class="badge ${t.kind === "global" ? "global" : ""}">${esc(t.kind === "global" ? "全局 · 自动写入" : "项目 · 需确认")}</span></div>
        <div class="meta"><code>${esc(t.document_id)}</code> · ${esc(t.vault_relpath)}</div></div></div>`).join("");
  }

  async function refreshClassify() {
    const [c, props, recent] = await Promise.all([
      get("/api/classify/stats").catch((e) => ({ reachable: false, error: e.message })),
      get("/api/classify/proposals").catch(() => []),
      get("/api/classify/recent?limit=40").catch(() => []),
    ]);
    renderClassify(c);
    renderProposals(props);
    renderRecent(recent);
  }

  async function refresh() {
    try {
      const health = await get("/api/health");
      $("health-pill").textContent = "ok · v" + health.version;
      $("health-pill").className = "pill ok";
    } catch {
      $("health-pill").textContent = "offline";
      $("health-pill").className = "pill warn";
    }
    const classifyP = refreshClassify();
    const [stats, inbox, filters, topics] = await Promise.all([
      get("/api/stats"), get("/api/inbox"), get("/api/filters"), get("/api/topics"),
    ]);
    renderPipeline(stats, filters);
    renderInbox(inbox);
    renderTopics(topics);
    await classifyP;
  }

  $("proposals-list").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("button[data-act]");
    if (!btn) return;
    const card = btn.closest(".prop");
    const id = card.dataset.id;
    const act = btn.dataset.act;
    let body = {};
    if (act === "approve") {
      if (!confirm("确认把这条建议写入 Obsidian？")) return;
    } else {
      const r = prompt("拒绝理由（可空）", "");
      if (r === null) return;
      body = { reason: r };
    }
    card.querySelectorAll("button").forEach((b) => (b.disabled = true));
    try {
      const res = await post(`/api/classify/proposals/${encodeURIComponent(id)}/${act}`, body);
      if (res.ok === false) throw new Error(res.error || "失败");
      toast(act === "approve" ? `已写入 ${res.target_path || ""}${res.base_changed ? "（目标笔记已变动，已按节合并）" : ""}` : "已拒绝");
      await refreshClassify();
    } catch (e) {
      toast("操作失败：" + e.message, true);
      card.querySelectorAll("button").forEach((b) => (b.disabled = false));
    }
  });

  const btnReasons = $("btn-reasons");
  btnReasons.addEventListener("click", () => {
    const open = btnReasons.getAttribute("aria-expanded") === "true";
    btnReasons.setAttribute("aria-expanded", open ? "false" : "true");
    $("filter-reasons").hidden = open;
    btnReasons.textContent = open ? "隔离原因 ▾" : "隔离原因 ▴";
  });
  $("btn-refresh").addEventListener("click", () => refresh().catch((e) => toast(e.message, true)));
  refresh().catch((e) => { console.error(e); toast("加载失败：" + e.message, true); });
})();
