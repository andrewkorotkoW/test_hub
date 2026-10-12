/*
 * project.html, вкладка «Запуск»: список стендов проекта, статус манер
 * manual_only (боевой stand — запуск только вручную с подтверждением,
 * см. app/core/runner.py::ManualRunNotConfirmed), модалка ручного
 * подтверждения запуска.
 */

  // ---------------- stands ----------------
  let standsByName = {};
  let standsList = [];
  let manualRunPresetItems = [];

  async function loadStands() {
    try {
      const stands = await api(`/api/projects/${encodeURIComponent(projectName)}/stands`);
      standsByName = {};
      standsList = stands;
      stands.forEach((s) => { standsByName[s.name] = s; });
      standSelect.innerHTML = `<option value="">— без стенда —</option>` +
        stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)} (${escapeHtml(s.url)})</option>`).join("");
      flakyStandSelect.innerHTML = `<option value="">— все стенды —</option>` +
        stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}</option>`).join("");
      schedStandSelect.innerHTML = `<option value="">— без стенда —</option>` +
        stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}</option>`).join("");
      if (canSeeSentry) {
        sentryStandSelect.innerHTML = `<option value="">— выберите стенд —</option>` +
          stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}</option>`).join("");
        if (stands.length) sentryStandSelect.value = stands[0].name;
      }
      await updateRunControlsForStand();
    } catch (err) {
      showPageError(`Не удалось загрузить стенды: ${err.message}`);
    }
  }

  // manual_only-стенд (боевой stage) — вместо мгновенного запуска показываем блок
  // с пресетами/выбором из дерева, каждый запуск идёт только через модалку
  // подтверждения (см. openManualRunModal ниже) и confirm_manual: true в теле POST.
  async function updateRunControlsForStand() {
    const stand = standsByName[standSelect.value];
    const isManual = !!(stand && stand.manual_only);
    runAllBtn.hidden = isManual || isBuildMode;
    runSelectedBtn.hidden = isManual;
    manualRunBlock.hidden = !isManual;
    if (!isManual) {
      manualRunPresetItems = [];
      return;
    }
    manualRunStandName.textContent = stand.name;
    manualRunPresets.innerHTML = `<span class="muted">Загрузка пресетов…</span>`;
    try {
      manualRunPresetItems = await api(
        `/api/projects/${encodeURIComponent(projectName)}/stands/${encodeURIComponent(stand.name)}/presets`
      );
      manualRunPresets.innerHTML = manualRunPresetItems.length
        ? manualRunPresetItems.map((p) => `<button type="button" class="manual-run-preset-btn" data-preset-id="${p.id}">${escapeHtml(p.name)}</button>`).join("")
        : `<span class="muted">Пресетов нет.</span>`;
    } catch (err) {
      manualRunPresetItems = [];
      manualRunPresets.innerHTML = `<span class="error-box">Не удалось загрузить пресеты: ${escapeHtml(err.message)}</span>`;
    }
  }

  standSelect.addEventListener("change", updateRunControlsForStand);

  function openManualRunModal({ label, stand, target, marker, runLabel = null }) {
    manualRunModalOverlay.dataset.pending = JSON.stringify({ stand, target, marker: marker || null, runLabel });
    manualRunModalText.textContent = `Запустить на ${stand}: ${label}. Это боевой тестовый стенд, запуск только вручную.`;
    manualRunConfirmCheckbox.checked = false;
    manualRunConfirmBtn.disabled = true;
    manualRunModalOverlay.hidden = false;
  }

  manualRunPresets.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".manual-run-preset-btn");
    if (!btn) return;
    const preset = manualRunPresetItems.find((p) => String(p.id) === btn.dataset.presetId);
    if (!preset) return;
    openManualRunModal({
      label: `пресет «${preset.name}»`,
      stand: standSelect.value,
      target: preset.target,
      marker: preset.marker,
    });
  });

  manualRunSelectedBtn.addEventListener("click", () => {
    const target = selectedTarget();
    if (!target) {
      alert("Отметьте хотя бы один раздел/файл или заполните ручное поле.");
      return;
    }
    openManualRunModal({
      label: "выбранные тесты",
      stand: standSelect.value,
      target,
      marker: markerSelect.value || null,
      runLabel: isBuildMode ? buildLabel : null,
    });
  });

  manualRunConfirmCheckbox.addEventListener("change", () => {
    manualRunConfirmBtn.disabled = !manualRunConfirmCheckbox.checked;
  });

  function closeManualRunModal() {
    manualRunModalOverlay.hidden = true;
    delete manualRunModalOverlay.dataset.pending;
  }

  manualRunCancelBtn.addEventListener("click", closeManualRunModal);
  manualRunModalOverlay.addEventListener("click", (ev) => {
    if (ev.target === manualRunModalOverlay) closeManualRunModal();
  });

  manualRunConfirmBtn.addEventListener("click", async () => {
    if (!manualRunConfirmCheckbox.checked || !manualRunModalOverlay.dataset.pending) return;
    const pending = JSON.parse(manualRunModalOverlay.dataset.pending);
    manualRunConfirmBtn.disabled = true;
    try {
      const run = await api(`/api/projects/${encodeURIComponent(projectName)}/runs`, {
        method: "POST",
        json: { stand: pending.stand, target: pending.target, marker: pending.marker, confirm_manual: true, label: pending.runLabel || null },
      });
      closeManualRunModal();
      await openRun(run.id);
      await loadHistory();
      await loadBuildRuns();
    } catch (err) {
      alert(`Не удалось запустить тесты: ${err.message}`);
      manualRunConfirmBtn.disabled = !manualRunConfirmCheckbox.checked;
    }
  });

  function isManualStandRun(standName) {
    const stand = standsByName[standName];
    return !!(stand && stand.manual_only);
  }

