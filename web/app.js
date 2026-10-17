/* hinddian dashboard — Magpie-like dense dark UI */
(function () {
  const $ = (id) => document.getElementById(id);

  async function get(path) {
    const res = await fetch(path, { headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error(path + " " + res.status);
    return res.json();
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return d.toLocaleString("zh-CN", { hour12: false });
    } catch {
      return iso;
    }
  }

  function statCard(label, value, cls) {
    return `<div class="stat"><div class="label">${esc(label)}</div>` +
      `<div class="value ${cls || ""}">${esc(value)}</div></div>`;
  }

  function renderStats(s) {
    const grid = $("stats-grid");
    grid.innerHTML = [
      statCard("收件箱", s.inbox_count, s.inbox_count > 0 ? "warn" : "ok"),
      statCard("隔离区", s.quarantine_count),
      statCard("已处理", s.processed_count, "ok"),
      statCard("失败", s.failed_count, s.failed_count ? "danger" : ""),
      statCard("提炼排队", s.jobs_pending, "warn"),
      statCard("提炼中", s.jobs_running, "info"),
      statCard("待入库", s.pending_ingests, s.pending_ingests ? "warn" : "ok"),
      statCard("主题数", s.topics_tracked),
    ].join("");
    $("demo-flag").textContent = s.demo
      ? "演示数据 · USE_DEMO_DATA"
      : "真实数据 · USE_DEMO_DATA=false";
  }

  function renderInbox(items) {
    $("inbox-count").textContent = String(items.length);
    if (!items.length) {
      $("inbox-list").innerHTML = `<p class="empty">收件箱为空</p>`;
      return;
    }
    $("inbox-list").innerHTML = items
      .map(
        (it) => `<div class="row">
          <div>
            <div class="title">${esc(it.title || it.id)}</div>
            <div class="meta">${esc(it.project || "—")} · ${esc(it.source || "?")} · ${esc(it.agent || "")} · ${fmtTime(it.received_at)}</div>
          </div>
          <span class="badge">${esc(it.bytes != null ? it.bytes + " B" : "")}</span>
        </div>`
      )
      .join("");
  }

  function renderFilters(rows) {
    const total = rows.reduce((a, r) => a + (r.count || 0), 0);
    $("filter-count").textContent = String(total);
    if (!rows.length) {
      $("filter-list").innerHTML = `<p class="empty">暂无过滤记录</p>`;
      return;
    }
    $("filter-list").innerHTML = rows
      .map(
        (r) => `<div class="row">
          <div>
            <div class="title"><code>${esc(r.reason)}</code></div>
            <div class="meta">${esc((r.examples || []).slice(0, 2).join(" · ") || "—")}</div>
          </div>
          <span class="badge">${esc(r.count)}</span>
        </div>`
      )
      .join("");
  }

  function renderJobs(jobs) {
    $("jobs-count").textContent = String(jobs.length);
    if (!jobs.length) {
      $("jobs-list").innerHTML = `<p class="empty">无任务</p>`;
      return;
    }
    $("jobs-list").innerHTML = jobs
      .map((j) => {
        const targets = (j.target_document_ids || []).map((id) => `<code>${esc(id)}</code>`).join(" ");
        return `<div class="row">
          <div>
            <div class="title">${esc(j.title || j.id)}</div>
            <div class="meta">${esc(j.project || "—")} · ${targets || "无目标主题"}${j.error ? " · " + esc(j.error) : ""}</div>
          </div>
          <span class="badge ${esc(j.status)}">${esc(j.status)}</span>
        </div>`;
      })
      .join("");
  }

  function renderTopics(topics) {
    $("topics-count").textContent = String(topics.length);
    if (!topics.length) {
      $("topics-list").innerHTML = `<p class="empty">无主题</p>`;
      return;
    }
    $("topics-list").innerHTML = topics
      .map((t) => {
        const kind = t.kind === "global" ? "global" : "";
        return `<div class="row">
          <div>
            <div class="title">${esc(t.title)} <span class="badge ${kind}">${esc(t.kind)}</span></div>
            <div class="meta"><code>${esc(t.document_id)}</code> · ${esc(t.vault_relpath)}</div>
          </div>
          <div style="text-align:right">
            <span class="badge ${esc(t.hindsight_state)}">${esc(t.hindsight_state)}</span>
            <div class="meta" style="margin-top:4px">待合并 ${esc(t.pending_merges)}</div>
          </div>
        </div>`;
      })
      .join("");
  }

  function renderMerges(merges) {
    if (!merges.length) {
      $("merges-list").innerHTML = `<p class="empty">暂无合并记录</p>`;
      return;
    }
    $("merges-list").innerHTML = merges
      .map(
        (m) => `<div class="row">
          <div>
            <div class="title">${esc(m.summary)}</div>
            <div class="meta"><code>${esc(m.document_id)}</code> · ${esc(m.session_id || "—")} · ${fmtTime(m.at)}</div>
          </div>
          <span class="badge ${esc(m.status)}">${esc(m.status)}</span>
        </div>`
      )
      .join("");
  }

  async function refresh() {
    try {
      const health = await get("/api/health");
      const pill = $("health-pill");
      pill.textContent = "ok · v" + health.version;
      pill.className = "pill ok";
    } catch (e) {
      const pill = $("health-pill");
      pill.textContent = "offline";
      pill.className = "pill warn";
    }

    const [stats, inbox, filters, jobs, topics, merges] = await Promise.all([
      get("/api/stats"),
      get("/api/inbox"),
      get("/api/filters"),
      get("/api/jobs"),
      get("/api/topics"),
      get("/api/merges"),
    ]);
    renderStats(stats);
    renderInbox(inbox);
    renderFilters(filters);
    renderJobs(jobs);
    renderTopics(topics);
    renderMerges(merges);
  }

  $("btn-refresh").addEventListener("click", () => {
    refresh().catch((e) => console.error(e));
  });

  refresh().catch((e) => {
    console.error(e);
    $("inbox-list").innerHTML = `<p class="empty">加载失败：${esc(e.message)}</p>`;
  });
})();
