/*
 * project.html, вкладка «Флаки»: нестабильные тесты проекта.
 */

  // ---------------- flaky tests ----------------
  function flakyDotsHtml(statuses) {
    return statuses.slice(-10).map((s) => `<span class="flaky-dot ${escapeHtml(s || "unknown")}" title="${escapeHtml(s)}"></span>`).join("");
  }

  function renderFlakyRows(items) {
    if (!items.length) {
      flakyRows.innerHTML = `<tr><td colspan="6" class="muted">Нестабильных тестов не найдено.</td></tr>`;
      return;
    }
    flakyRows.innerHTML = items.map((item) => {
      const percent = Math.round(item.score * 100);
      const shortName = item.test.split("#").pop();
      const rowClass = item.score >= FLAKY_THRESHOLD ? "flaky-high" : "";
      const runBtn = item.nodeid
        ? `<button class="flaky-run-btn" data-nodeid="${escapeHtml(item.nodeid)}" data-stand="${escapeHtml(item.stand)}">Прогнать ×3</button>`
        : "—";
      return `
        <tr class="${rowClass}">
          <td title="${escapeHtml(item.test)}">${escapeHtml(shortName)}</td>
          <td class="num-col">${item.runs}</td>
          <td class="num-col">${item.fails}</td>
          <td class="num-col">${percent}%</td>
          <td class="flaky-dots">${flakyDotsHtml(item.last_statuses)}</td>
          <td>${runBtn}</td>
        </tr>
      `;
    }).join("");
  }

  async function loadFlaky() {
    flakyError.hidden = true;
    try {
      const params = new URLSearchParams({ min_runs: "3" });
      if (flakyStandSelect.value) params.set("stand", flakyStandSelect.value);
      const data = await api(`/api/projects/${encodeURIComponent(projectName)}/flaky?${params}`);
      renderFlakyRows(data.items || []);
    } catch (err) {
      flakyRows.innerHTML = "";
      flakyError.textContent = `Не удалось загрузить нестабильные тесты: ${err.message}`;
      flakyError.hidden = false;
    }
  }

  flakyStandSelect.addEventListener("change", loadFlaky);

  flakyRows.addEventListener("click", async (ev) => {
    const btn = ev.target.closest(".flaky-run-btn");
    if (!btn) return;
    btn.disabled = true;
    try {
      const run = await api(`/api/projects/${encodeURIComponent(projectName)}/runs`, {
        method: "POST",
        json: { stand: btn.dataset.stand || null, target: btn.dataset.nodeid, repeat: 3 },
      });
      await openRun(run.id);
      await loadHistory();
    } catch (err) {
      alert(`Не удалось запустить прогон: ${err.message}`);
    } finally {
      btn.disabled = false;
    }
  });

