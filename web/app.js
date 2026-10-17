/* hinddian dashboard — Magpie-like pipeline UI */
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

  function setCount(el, n, clsWhenPositive) {
    const v = Number(n) || 0;
    el.textContent = String(v);
    el.className = "stage-count" + (v === 0 ? " zero" : clsWhenPositive ? " " + clsWhenPositive : "");
  }

  function setSplit(el, n) {
    el.textContent = String(Number(n) || 0);
  }

  function renderPipeline(s, filters) {
    const inbox = s.inbox_count || 0;
    setCount($("pipe-inbox"), inbox, inbox > 0 ? "" : "ok");
    if (inbox === 0) $("pipe-inbox").classList.add("ok");

    const q = s.quarantine_count || 0;
    const qEl = $("pipe-quarantine");
    qEl.textContent = String(q);
    qEl.className = "stage-count" + (q === 0 ? " zero" : "");
    setSplit($("pipe-pending"), s.jobs_pending || 0);
    setSplit($("pipe-running"), s.jobs_running || 0);
    setSplit($("pipe-processed"), s.processed_count || 0);
    setSplit($("pipe-failed"), s.failed_count || 0);

    const jobTrackEmpty =
      !(s.jobs_pending || s.jobs_running || s.jobs_done || s.jobs_failed);
    $("distill-note").textContent = jobTrackEmpty
      ? "任务跟踪可能仍为 stub（sqlite 无 job）"
      : "sqlite 任务 · pending / running / done / failed";

    // demo pill
    const demoPill = $("demo-pill");
    if (s.demo) {
      demoPill.textContent = "demo: true";
      demoPill.className = "pill demo";
    } else {
      demoPill.textContent = "demo: false · 真实数据";
      demoPill.className = "pill live";
    }
    $("demo-flag").textContent = s.demo
      ? "演示数据 · USE_DEMO_DATA"
      : "真实数据 · USE_DEMO_DATA=false";

    // quarantine reasons under filter stage
    const box = $("filter-reasons");
    if (!filters || !filters.length) {
      box.innerHTML = `<div class="reason-row"><span class="empty" style="padding:8px 0">暂无隔离原因</span></div>`;
    } else {
      box.innerHTML = filters
        .map(
          (r) => `<div class="reason-row">
            <code>${esc(r.reason)}</code>
            <span class="reason-n">${esc(r.count)}</span>
          </div>`
        )
        .join("");
    }
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

  function renderJobs(jobs) {
    $("jobs-count").textContent = String(jobs.length);
    if (!jobs.length) {
      $("jobs-list").innerHTML = `<p class="empty">无任务 · 提炼 job 跟踪可能尚未接入</p>`;
      return;
    }
    $("jobs-list").innerHTML = jobs
      .map((j) => {
        const targets = (j.target_document_ids || [])
          .map((id) => `<code>${esc(id)}</code>`)
          .join(" ");
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
    renderPipeline(stats, filters);
    renderInbox(inbox);
    renderJobs(jobs);
    renderTopics(topics);
    renderMerges(merges);
  }

  const btnReasons = $("btn-reasons");
  const reasonsBox = $("filter-reasons");
  btnReasons.addEventListener("click", () => {
    const open = btnReasons.getAttribute("aria-expanded") === "true";
    btnReasons.setAttribute("aria-expanded", open ? "false" : "true");
    reasonsBox.hidden = open;
    btnReasons.textContent = open ? "隔离原因 ▾" : "隔离原因 ▴";
  });

  $("btn-refresh").addEventListener("click", () => {
    refresh().catch((e) => console.error(e));
  });

  refresh().catch((e) => {
    console.error(e);
    $("inbox-list").innerHTML = `<p class="empty">加载失败：${esc(e.message)}</p>`;
  });
})();
