(async function () {
  const params = new URLSearchParams(window.location.search);
  const projectName = params.get("name");
  if (!projectName) {
    window.location.href = "projects.html";
    return;
  }

  const user = await initPage();
  const canDecide = user.role === "qa" || user.role === "manager" || user.role === "superadmin";

  document.getElementById("project-title").textContent = `Новые дефекты — ${projectName}`;
  document.getElementById("project-link").href = `project.html?name=${encodeURIComponent(projectName)}`;

  api("/api/projects").then((projects) => {
    const current = projects.find((p) => p.name === projectName);
    if (current) applyProjectColor(current.color);
  }).catch(() => { /* без цвета проекта остаётся дефолтный акцент из style.css */ });

  const standSelect = document.getElementById("nd-stand-select");
  const runSelect = document.getElementById("nd-run-select");
  const toolbarMsg = document.getElementById("nd-toolbar-msg");
  const listBox = document.getElementById("nd-list");

  let youtrackConnected = true;

  function showToolbarMsg(message, isError) {
    toolbarMsg.textContent = message;
    toolbarMsg.hidden = false;
    toolbarMsg.classList.toggle("error-box", !!isError);
    toolbarMsg.classList.toggle("hint-box", !isError);
  }

  function hideToolbarMsg() {
    toolbarMsg.hidden = true;
  }

  const SEVERITY_CLASS = {
    Blocker: "sev-critical", Critical: "sev-critical",
    Major: "sev-major", Minor: "sev-minor", Trivial: "sev-minor",
  };

  function severityBadgeHtml(severity) {
    if (!severity) return "";
    const cls = SEVERITY_CLASS[severity] || "sev-minor";
    return `<span class="badge ${cls}">${escapeHtml(severity)}</span>`;
  }

  function areaBadgeHtml(area) {
    return area === "front" ? `<span class="badge nd-front">Front</span>` : `<span class="badge nd-back">Back</span>`;
  }

  function stepsHtml(steps) {
    if (!steps.length) return "";
    return `<ul class="nd-steps">` + steps.map((s) => {
      const cls = s.status === "failed" || s.status === "broken" ? "nd-step-failed" : "nd-step-passed";
      return `<li class="${cls}">${escapeHtml(s.name || "")}</li>`;
    }).join("") + `</ul>`;
  }

  function defaultPrecondition(steps) {
    const passed = steps.filter((s) => s.status === "passed" && s.name);
    if (!passed.length) return "";
    return passed.map((s, i) => `${i + 1} - ${s.name}`).join("\n");
  }

  function shortName(fullName) {
    return (fullName || "").split("#").pop();
  }

  function cardHtml(item) {
    const fr = (item.message || "").trim();
    return `
      <div class="card nd-card" data-full-name="${escapeHtml(item.full_name)}" data-run-id="${item.run_id}">
        <div class="nd-card-head">
          <div>
            <div class="nd-card-title">${escapeHtml(shortName(item.full_name))}</div>
            <div class="nd-card-path">${escapeHtml(item.nodeid)}</div>
          </div>
          <div class="nd-badges">
            ${areaBadgeHtml(item.area)}
            ${severityBadgeHtml(item.severity)}
          </div>
        </div>
        ${stepsHtml(item.steps)}
        ${fr ? `<div class="nd-fr-box">${escapeHtml(fr)}</div>` : ""}
        <div class="nd-field-grid">
          <div class="field">
            <label>Приоритет</label>
            <select class="nd-priority">
              <option value="">— выбрать —</option>
              <option value="Высокий">Высокий</option>
              <option value="Средний">Средний</option>
              <option value="Низкий">Низкий</option>
            </select>
          </div>
          <div class="field">
            <label>Серьёзность <span class="nd-auto-tag">авто</span></label>
            <input value="${escapeHtml(item.severity || "—")}" disabled>
          </div>
          <div class="field nd-span2">
            <label>Пред_условие <span class="nd-auto-tag">авто из allure.steps</span></label>
            <textarea class="nd-precondition">${escapeHtml(defaultPrecondition(item.steps))}</textarea>
          </div>
          <div class="field nd-span2">
            <label>ОР (ожидаемый результат)</label>
            <textarea class="nd-expected" placeholder="Что должно было произойти"></textarea>
          </div>
        </div>
        <div class="nd-card-foot">
          <div class="muted">прогон <code>#${item.run_id}</code></div>
          <div class="nd-actions">
            <button type="button" class="nd-skip-btn">Пропустить</button>
            <button type="button" class="primary nd-confirm-btn" ${youtrackConnected ? "" : "disabled"}>Подтвердить баг</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderList(items) {
    if (!items.length) {
      listBox.innerHTML = `<p class="muted">Новых дефектов не найдено — либо прогон чист, либо все уже разобраны.</p>`;
      return;
    }
    listBox.innerHTML = items.map(cardHtml).join("");
  }

  async function loadStands() {
    try {
      const stands = await api(`/api/projects/${encodeURIComponent(projectName)}/stands`);
      standSelect.innerHTML = `<option value="">— выберите стенд —</option>` +
        stands.map((s) => `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}</option>`).join("");
    } catch (err) {
      showPageError(`Не удалось загрузить стенды: ${err.message}`);
    }
  }

  async function loadRunsForStand(standName) {
    runSelect.innerHTML = `<option value="">—</option>`;
    if (!standName) return;
    try {
      const runs = await api(`/api/projects/${encodeURIComponent(projectName)}/runs`);
      const completed = runs.filter((r) => r.stand === standName && (r.status === "passed" || r.status === "failed"));
      runSelect.innerHTML = completed.map((r) =>
        `<option value="${r.id}">#${r.id} (${escapeHtml(r.status)})</option>`
      ).join("") || `<option value="">нет завершённых прогонов</option>`;
      if (completed.length) {
        runSelect.value = String(completed[0].id);
        await loadList();
      } else {
        listBox.innerHTML = "";
      }
    } catch (err) {
      showPageError(`Не удалось загрузить прогоны: ${err.message}`);
    }
  }

  async function loadList() {
    hideToolbarMsg();
    const stand = standSelect.value;
    const runId = runSelect.value;
    if (!stand || !runId) {
      listBox.innerHTML = "";
      return;
    }
    try {
      const data = await api(
        `/api/projects/${encodeURIComponent(projectName)}/new-defects?stand=${encodeURIComponent(stand)}&run_id=${runId}`
      );
      youtrackConnected = !!data.connected;
      if (!youtrackConnected) {
        showToolbarMsg(data.reason || "YouTrack не подключён — подтверждать нельзя, но можно смотреть и пропускать.", true);
      }
      renderList(data.items || []);
    } catch (err) {
      listBox.innerHTML = "";
      showPageError(`Не удалось загрузить новые дефекты: ${err.message}`);
    }
  }

  standSelect.addEventListener("change", () => loadRunsForStand(standSelect.value));
  runSelect.addEventListener("change", loadList);

  listBox.addEventListener("click", async (ev) => {
    const card = ev.target.closest(".nd-card");
    if (!card) return;
    const fullName = card.dataset.fullName;
    const runId = Number(card.dataset.runId);

    const skipBtn = ev.target.closest(".nd-skip-btn");
    const confirmBtn = ev.target.closest(".nd-confirm-btn");
    if (!skipBtn && !confirmBtn) return;

    const btn = skipBtn || confirmBtn;
    btn.disabled = true;
    try {
      const body = {
        full_name: fullName,
        run_id: runId,
        status: skipBtn ? "dismissed" : "confirmed",
        priority: card.querySelector(".nd-priority").value || null,
        expected_result: card.querySelector(".nd-expected").value.trim() || null,
        precondition: card.querySelector(".nd-precondition").value.trim() || null,
      };
      const result = await api(`/api/projects/${encodeURIComponent(projectName)}/new-defects/decide?stand=${encodeURIComponent(standSelect.value)}`, {
        method: "POST",
        json: body,
      });
      card.remove();
      if (!listBox.children.length) {
        listBox.innerHTML = `<p class="muted">Новых дефектов не найдено — либо прогон чист, либо все уже разобраны.</p>`;
      }
      if (result.status === "confirmed" && result.issue_url) {
        showToolbarMsg(`Отправлено в YouTrack: ${result.issue_url}`, false);
      }
    } catch (err) {
      showToolbarMsg(`Не удалось сохранить решение: ${err.message}`, true);
      btn.disabled = false;
    }
  });

  await loadStands();
})();
