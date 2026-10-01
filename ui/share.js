// Публичная страница отчёта прогона (без логина, только чтение) — app/routers/share.py.
// Не использует initPage()/requireAuth() из common.js: ссылка должна открываться без сессии.
(function () {
  const parts = window.location.pathname.split("/").filter(Boolean); // ["share", "<token>"]
  const token = parts[1];

  const pageError = document.getElementById("page-error");
  const runCard = document.getElementById("run-card");
  const runTitle = document.getElementById("run-title");
  const runMeta = document.getElementById("run-meta");
  const reportChart = document.getElementById("report-chart");
  const badgesBox = document.getElementById("summary-badges");
  const reportRows = document.getElementById("report-rows");
  const statusFilter = document.getElementById("report-status-filter");
  const allureLink = document.getElementById("allure-link");
  const liveFrameBox = document.getElementById("live-frame-box");
  const liveFrameImg = document.getElementById("live-frame-img");

  let currentTests = [];
  let liveTimer = null;
  let liveObjectUrl = null;

  // Живой кадр (docs/missions/2026-10-01_live_stream.md, п.5) — на share-странице нет
  // сессии и WS-подключения (public_router без Depends(get_current_user)), поэтому
  // вместо WS-сообщений просто опрашиваем /share/<token>/live.jpg раз в 2 с, пока он
  // есть в data.json (сервер отдаёт его там же, только пока run.status == "running").
  function startLivePolling(liveFrameUrl) {
    liveFrameBox.hidden = false;
    const tick = async () => {
      try {
        const resp = await fetch(`${liveFrameUrl}?t=${Date.now()}`);
        if (!resp.ok) return;
        const blob = await resp.blob();
        if (liveObjectUrl) URL.revokeObjectURL(liveObjectUrl);
        liveObjectUrl = URL.createObjectURL(blob);
        liveFrameImg.src = liveObjectUrl;
      } catch { /* сеть моргнула — попробуем на следующем тике */ }
    };
    tick();
    liveTimer = setInterval(tick, 2000);
  }

  function showError(message) {
    pageError.textContent = message;
    pageError.hidden = false;
  }

  function renderRows() {
    const status = statusFilter.value;
    const rows = currentTests.filter((t) => !status || t.status === status);
    if (!rows.length) {
      reportRows.innerHTML = `<tr><td colspan="3" class="muted">Нет тестов, соответствующих фильтру.</td></tr>`;
      return;
    }
    reportRows.innerHTML = rows.map((t, i) => `
      <tr class="clickable" data-idx="${i}">
        <td>${escapeHtml(t.name)}</td>
        <td class="status-text ${escapeHtml(t.status)}">${escapeHtml(t.status)}</td>
        <td>${fmtDuration(t.duration)}</td>
      </tr>
    `).join("");
    reportRows.dataset.rows = JSON.stringify(rows);
  }

  reportRows.addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr.clickable");
    if (!tr) return;
    const rows = JSON.parse(reportRows.dataset.rows || "[]");
    const test = rows[Number(tr.dataset.idx)];
    const next = tr.nextElementSibling;
    if (next && next.classList.contains("report-detail-row")) {
      next.remove();
      return;
    }
    document.querySelectorAll(".report-detail-row").forEach((el) => el.remove());
    const detail = document.createElement("tr");
    detail.className = "report-detail-row";
    const videoHtml = test.has_video
      ? `<div class="test-video">
          <video controls src="${escapeHtml(test.video_url)}"></video>
          <div class="test-video-meta">
            ${test.video_duration_ms != null ? `<span class="muted">${fmtDuration(test.video_duration_ms / 1000)}</span>` : ""}
            <a href="${escapeHtml(test.video_url)}" download class="video-download-link">Скачать</a>
          </div>
        </div>`
      : "";
    detail.innerHTML = `<td colspan="3">${videoHtml}<pre class="trace-pre">${escapeHtml(test.message || "Подробностей нет.")}</pre></td>`;
    tr.after(detail);
  });

  statusFilter.addEventListener("change", renderRows);

  (async function load() {
    if (!token) {
      showError("Ссылка недействительна.");
      return;
    }
    let data;
    try {
      data = await api(`/share/${encodeURIComponent(token)}/data.json`);
    } catch (err) {
      showError(
        err.status === 404
          ? "Ссылка недействительна, отозвана или срок её действия истёк."
          : `Не удалось загрузить отчёт: ${err.message}`
      );
      return;
    }

    runCard.hidden = false;
    const run = data.run || {};
    runTitle.textContent = `${run.project || "?"} — прогон #${run.id ?? "?"}`;
    runMeta.textContent = [
      run.stand ? `стенд: ${run.stand}` : "без стенда",
      `начат: ${fmtDate(run.started)}`,
      `длительность: ${fmtDuration(run.duration)}`,
    ].join(" · ");

    reportChart.src = data.report_png_url || `/share/${encodeURIComponent(token)}/report.png`;
    reportChart.hidden = false;

    const counts = data.counts || {};
    badgesBox.innerHTML = ["passed", "failed", "broken", "skipped"]
      .map((s) => `<span class="badge ${s}">${s}: ${counts[s] || 0}</span>`)
      .join("");

    if (data.allure_url) {
      allureLink.href = data.allure_url;
      allureLink.hidden = false;
    }

    currentTests = (data.tests || []).map((t) => ({
      ...t,
      video_url: `/share/${encodeURIComponent(token)}/tests/${encodeURIComponent(t.nodeid)}/video`,
    }));
    renderRows();

    if (data.live_frame_url) startLivePolling(data.live_frame_url);
  })();
})();
