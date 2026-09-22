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

  let currentTests = [];

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
    detail.innerHTML = `<td colspan="3"><pre class="trace-pre">${escapeHtml(test.message || "Подробностей нет.")}</pre></td>`;
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

    currentTests = data.tests || [];
    renderRows();
  })();
})();
