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
  const liveFrameArea = document.getElementById("live-frame-area");

  let currentTests = [];
  let liveTimer = null;
  let liveObjectUrl = null;
  let liveFrameImg = null;
  // run.mobile (docs/missions/2026-10-06_mobile_frame.md, п.3) — рамка Pixel 7 вокруг
  // кадра эфира/видео, тот же приём, что в ui/project.js::maybePhoneFrame, только здесь
  // у статус-бара нет ts кадра (контракт /share/<token>/live.jpg отдаёт бинарный jpeg,
  // не JSON, и его менять нельзя) — показываем время получения кадра на клиенте.
  let runMobile = false;

  const PHONE_FRAME_OFF_KEY = "th_phone_frame_off";
  function isPhoneFrameOff() {
    try { return localStorage.getItem(PHONE_FRAME_OFF_KEY) === "1"; } catch { return false; }
  }
  function setPhoneFrameOff(off) {
    try { localStorage.setItem(PHONE_FRAME_OFF_KEY, off ? "1" : "0"); } catch { /* localStorage недоступен */ }
  }

  // Без id у кнопки — она попадает и в #live-frame-area, и (отдельным экземпляром) в
  // открытую строку с видео теста, document.getElementById с дублирующимся id был бы
  // неоднозначен; клик ловим делегированием на document (см. ниже).
  function maybePhoneFrame(innerHtml, timeText) {
    if (!runMobile) return innerHtml;
    const off = isPhoneFrameOff();
    const toggleRow = `
      <div class="phone-frame-toggle-row">
        <button type="button" class="phone-frame-toggle-btn">${off ? "Показать рамку" : "Без рамки"}</button>
      </div>`;
    if (!RunLiveLogic.phoneFrameEnabled(runMobile, off)) return toggleRow + innerHtml;
    return `${toggleRow}
      <div class="phone-frame-wrap">
        <div class="phone-frame">
          <div class="phone-frame-statusbar">${escapeHtml(timeText || "")}</div>
          <div class="phone-frame-screen">${innerHtml}</div>
        </div>
      </div>`;
  }

  let liveActive = false;

  function renderLiveFrameArea() {
    const inner = `
      <div id="live-frame-box" class="live-frame"${liveActive ? "" : " hidden"}>
        <div class="live-frame-head">
          <span id="live-frame-badge" class="status-pill running">В эфире</span>
          <span class="muted">обновляется автоматически, пока прогон идёт</span>
        </div>
        <img id="live-frame-img" class="live-frame-img" alt="Живой кадр прогона">
      </div>`;
    liveFrameArea.innerHTML = maybePhoneFrame(inner, "");
    liveFrameImg = document.getElementById("live-frame-img");
  }

  // Переключатель «Без рамки» общий для кадра эфира и плеера видео теста (один
  // ключ localStorage, как в ui/project.js) — клик где угодно на странице
  // перестраивает кадр эфира и, если открыта строка с видео, её тоже.
  document.addEventListener("click", (ev) => {
    if (!ev.target.closest(".phone-frame-toggle-btn")) return;
    setPhoneFrameOff(!isPhoneFrameOff());
    renderLiveFrameArea();
    const openDetail = reportRows.querySelector(".report-detail-row");
    if (openDetail) {
      const idx = openDetail.dataset.forIdx;
      const tr = reportRows.querySelector(`tr.clickable[data-idx="${idx}"]`);
      if (tr) openDetailRow(tr);
    }
  });

  // Живой кадр (docs/missions/2026-10-01_live_stream.md, п.5) — на share-странице нет
  // сессии и WS-подключения (public_router без Depends(get_current_user)), поэтому
  // вместо WS-сообщений просто опрашиваем /share/<token>/live.jpg раз в 2 с, пока он
  // есть в data.json (сервер отдаёт его там же, только пока run.status == "running").
  function startLivePolling(liveFrameUrl) {
    liveActive = true;
    document.getElementById("live-frame-box").hidden = false;
    const tick = async () => {
      try {
        const resp = await fetch(`${liveFrameUrl}?t=${Date.now()}`);
        if (!resp.ok) return;
        const blob = await resp.blob();
        if (liveObjectUrl) URL.revokeObjectURL(liveObjectUrl);
        liveObjectUrl = URL.createObjectURL(blob);
        liveFrameImg.src = liveObjectUrl;
        const statusbar = document.querySelector("#live-frame-area .phone-frame-statusbar");
        if (statusbar) statusbar.textContent = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
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
    const next = tr.nextElementSibling;
    if (next && next.classList.contains("report-detail-row")) {
      next.remove();
      return;
    }
    openDetailRow(tr);
  });

  function openDetailRow(tr) {
    const rows = JSON.parse(reportRows.dataset.rows || "[]");
    const test = rows[Number(tr.dataset.idx)];
    document.querySelectorAll(".report-detail-row").forEach((el) => el.remove());
    const detail = document.createElement("tr");
    detail.className = "report-detail-row";
    detail.dataset.forIdx = tr.dataset.idx;
    const videoHtml = test.has_video
      ? maybePhoneFrame(
          `<div class="test-video">
            <video controls src="${escapeHtml(test.video_url)}"></video>
            <div class="test-video-meta">
              ${test.video_duration_ms != null ? `<span class="muted">${fmtDuration(test.video_duration_ms / 1000)}</span>` : ""}
              <a href="${escapeHtml(test.video_url)}" download class="video-download-link">Скачать</a>
            </div>
          </div>`,
          ""
        )
      : "";
    detail.innerHTML = `<td colspan="3">${videoHtml}<pre class="trace-pre">${escapeHtml(test.message || "Подробностей нет.")}</pre></td>`;
    tr.after(detail);
  }

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
    runMobile = Boolean(run.mobile);
    renderLiveFrameArea();
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
