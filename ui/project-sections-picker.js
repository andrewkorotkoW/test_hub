/*
 * project.html: виджет дерева разделов (api/ui/e2e -> области -> файлы) —
 * чекбоксы выбора целей прогона/расписания. Чистая логика (поиск/пресеты/
 * сборка target/имена/раскрытые узлы) — в sections-tree-logic.js (window.
 * SectionsTreeLogic), подключённом раньше этого файла.
 *
 * createSectionsPicker используется дважды — для формы «Запуска» (sectionsPicker)
 * и формы «Расписаний» (schedSectionsPicker, ui/project-setup.js) — второй
 * обращается к объекту отсюда только из обработчика клика (schedCreateBtn),
 * то есть уже после того, как этот файл загрузится и создаст оба пикера.
 */

  // ---------------- дерево разделов (api/ui/e2e -> области -> файлы) ----------------
  // Чистая логика (поиск/пресеты/сборка target/имена/раскрытые узлы) —
  // в sections-tree-logic.js (window.SectionsTreeLogic), подключённом раньше
  // этого файла; здесь только DOM (разметка, раскрытие, подсчёт «выбрано N из M»).
  const KIND_LABELS = { api: "tests/api", ui: "tests/ui", e2e: "tests/e2e" };

  function sectionMetaText(area) {
    const base = `${area.tests_count} тест.`;
    if (!area.status) return base;
    const pct = area.status.passed_percent;
    return `${base} · последний прогон: ${pct === null || pct === undefined ? "—" : pct + "% passed"}`;
  }

  function nodeHeadHtml(opts) {
    return `
      <div class="tree-node-head" role="button" tabindex="0" aria-expanded="${opts.open ? "true" : "false"}">
        <span class="tree-chev" aria-hidden="true">▸</span>
        <input type="checkbox" class="tree-check tree-parent" aria-label="Выбрать ${escapeHtml(opts.ariaLabel)} целиком">
        <span class="tree-node-title"${opts.title ? ` title="${escapeHtml(opts.title)}"` : ""}>${escapeHtml(opts.label)}</span>
        <span class="tree-meta muted"><span class="tree-node-meta-base">${escapeHtml(opts.baseMeta)}</span> · <span class="tree-node-meta-count">${escapeHtml(opts.countText)}</span></span>
      </div>
    `;
  }

  function countText(checkedCount, total) {
    return `выбрано ${checkedCount} из ${total}`;
  }

  // Раскрытые узлы (expandedKeys — Set из SectionsTreeLogic.kindNodeKey/areaNodeKey,
  // уже объединяет ручные клики и авто-раскрытие по поиску, см. createSectionsPicker)
  // переживают пересборку innerHTML — ключ раскрытия хранится вне разметки.
  function buildSectionsTreeHtml(filtered, checkedTargets, expandedKeys) {
    if (!filtered.kinds.length) return `<p class="muted">Разделы не найдены.</p>`;
    return filtered.kinds.map((kindNode) => {
      const kindFiles = SectionsTreeLogic.kindAllFiles(kindNode);
      const kindTestsCount = kindNode.areas.reduce((sum, a) => sum + (a.tests_count || 0), 0);
      const kindKey = SectionsTreeLogic.kindNodeKey(kindNode);
      const kindOpen = expandedKeys.has(kindKey);
      const kindLabel = KIND_LABELS[kindNode.kind] || kindNode.kind;

      const areasHtml = kindNode.areas.map((area) => {
        const filesHtml = area.files.map((file) => `
          <label title="${escapeHtml(file.target)}"><input type="checkbox" class="tree-check tree-leaf" data-target="${escapeHtml(file.target)}" ${checkedTargets.has(file.target) ? "checked" : ""}> ${escapeHtml(SectionsTreeLogic.fileLabel(file.name))}</label>
        `).join("");
        if (area.area == null) {
          // e2e: один псевдо-раздел без промежуточного узла области, файлы сразу.
          return `<div class="tree-tests">${filesHtml}</div>`;
        }
        const areaKey = SectionsTreeLogic.areaNodeKey(kindNode, area);
        const areaOpen = expandedKeys.has(areaKey);
        const areaLabel = SectionsTreeLogic.areaLabel(area.area);
        const areaChecked = SectionsTreeLogic.countChecked(area.files, checkedTargets);
        return `
          <div class="tree-class${areaOpen ? " open" : ""}" data-tree-key="${escapeHtml(areaKey)}">
            ${nodeHeadHtml({
              open: areaOpen,
              ariaLabel: areaLabel,
              label: areaLabel,
              title: area.section || area.area,
              baseMeta: sectionMetaText(area),
              countText: countText(areaChecked, area.files.length),
            })}
            <div class="tree-tests"${areaOpen ? "" : " hidden"}>${filesHtml}</div>
          </div>
        `;
      }).join("");

      const kindChecked = SectionsTreeLogic.countChecked(kindFiles, checkedTargets);
      return `
        <div class="tree-file${kindOpen ? " open" : ""}" data-tree-key="${escapeHtml(kindKey)}">
          ${nodeHeadHtml({
            open: kindOpen,
            ariaLabel: kindLabel,
            label: kindLabel,
            baseMeta: `${kindTestsCount} тест.`,
            countText: countText(kindChecked, kindFiles.length),
          })}
          <div class="tree-classes"${kindOpen ? "" : " hidden"}>${areasHtml}</div>
        </div>
      `;
    }).join("");
  }

  function setParentState(parentCb, leaves) {
    if (!parentCb || !leaves.length) return;
    const checkedCount = Array.from(leaves).filter((cb) => cb.checked).length;
    parentCb.checked = checkedCount === leaves.length;
    parentCb.indeterminate = checkedCount > 0 && checkedCount < leaves.length;
  }

  function updateCountLabel(scope, leaves) {
    const countEl = scope.querySelector(":scope > .tree-node-head .tree-node-meta-count");
    if (!countEl) return;
    const checkedCount = Array.from(leaves).filter((cb) => cb.checked).length;
    countEl.textContent = countText(checkedCount, leaves.length);
  }

  function updateAncestors(checkbox) {
    const classScope = checkbox.closest("div.tree-class");
    if (classScope) {
      const leaves = classScope.querySelectorAll(".tree-tests input.tree-leaf");
      setParentState(classScope.querySelector(":scope > .tree-node-head > input.tree-check"), leaves);
      updateCountLabel(classScope, leaves);
    }
    const fileScope = checkbox.closest("div.tree-file");
    if (fileScope) {
      const leaves = fileScope.querySelectorAll(".tree-leaf");
      setParentState(fileScope.querySelector(":scope > .tree-node-head > input.tree-check"), leaves);
      updateCountLabel(fileScope, leaves);
    }
  }

  // После полной пересборки innerHTML (рендер дерева заново — поиск/пресет/раскрытие)
  // родительские чекбоксы (область/раздел) рендерятся как ни на что не похожие
  // на состояние листьев — buildSectionsTreeHtml знает только про checked-атрибут
  // самих файлов (счётчики «выбрано N из M» он, в отличие от checked/indeterminate,
  // уже посчитал сам). Эта функция досчитывает checked/indeterminate у всех
  // .tree-class/.tree-file по уже отрисованным листьям, как updateAncestors
  // делает для одного изменения.
  function syncAllAncestors(box) {
    box.querySelectorAll("div.tree-class").forEach((classScope) => {
      setParentState(
        classScope.querySelector(":scope > .tree-node-head > input.tree-check"),
        classScope.querySelectorAll(".tree-tests input.tree-leaf")
      );
    });
    box.querySelectorAll("div.tree-file").forEach((fileScope) => {
      setParentState(
        fileScope.querySelector(":scope > .tree-node-head > input.tree-check"),
        fileScope.querySelectorAll(".tree-leaf")
      );
    });
  }

  // handlers.onHeaderToggle(key) — клик/Enter/Space по заголовку узла (не по
  // чекбоксу — ev.target.matches("input.tree-check") возвращает раньше, поэтому
  // ниже не нужен preventDefault/stopImmediatePropagation, чекбокс и раскрытие
  // не конфликтуют). handlers.onLeafChange() — после updateAncestors на каждое
  // ручное изменение листа, для пересчёта строки итога.
  function setupTreeEvents(box, handlers) {
    const onHeaderToggle = (handlers && handlers.onHeaderToggle) || null;
    const onLeafChange = (handlers && handlers.onLeafChange) || null;
    const toggleFromEvent = (ev) => {
      if (ev.target.matches("input.tree-check")) { ev.stopPropagation(); return; }
      const head = ev.target.closest(".tree-node-head");
      if (!head || !onHeaderToggle) return;
      const node = head.closest("[data-tree-key]");
      if (node) onHeaderToggle(node.dataset.treeKey);
    };
    box.addEventListener("click", toggleFromEvent);
    box.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      if (!ev.target.matches(".tree-node-head")) return;
      ev.preventDefault();
      toggleFromEvent(ev);
    });
    box.addEventListener("change", (ev) => {
      const checkbox = ev.target;
      if (!checkbox.matches("input.tree-check")) return;
      if (checkbox.classList.contains("tree-parent")) {
        const scope = checkbox.closest("div.tree-class") || checkbox.closest("div.tree-file");
        scope.querySelectorAll("input.tree-check").forEach((cb) => {
          if (cb !== checkbox) { cb.checked = checkbox.checked; cb.indeterminate = false; }
        });
      }
      updateAncestors(checkbox);
      if (onLeafChange) onLeafChange();
    });
  }

  function checkedFileTargets(box) {
    return Array.from(box.querySelectorAll(".tree-leaf:checked")).map((cb) => cb.dataset.target);
  }

  // Числа тестов продукта справа у кнопок L/H/R/Всё в ряду «Что»
  // (SectionsTreeLogic.productTestCounts) — моноширинным, как в макете.
  function updateProductCounts(row, data) {
    if (!row) return;
    const counts = SectionsTreeLogic.productTestCounts(data);
    row.querySelectorAll(".preset-count").forEach((el) => {
      const product = el.dataset.countFor;
      el.textContent = counts[product] != null ? String(counts[product]) : "";
    });
  }

  // Пикер дерева разделов используется дважды (форма запуска и форма расписания) —
  // общий стейт (данные с бэкенда + текущий поиск + отмеченные файлы + раскрытые
  // узлы + продукт/вид) и рендер под конкретную группу DOM-элементов. opts.mobile
  // (по умолчанию true) — есть ли в kindsRow кнопка «Mobile»: у расписания её нет
  // в разметке (ui/project.html), флаг — просто защита от программного клика.
  // opts.onStateChange зовётся после каждого render() — у формы запуска сюда
  // подвешен updateBuildChip() (ui/project-run-window.js) для чипа «Сборка: …».
  function createSectionsPicker(box, searchInput, productsRow, kindsRow, markerSelectEl, summaryLineEl, opts) {
    const { mobile = true, onStateChange = null } = opts || {};
    let data = { kinds: [] };
    let query = "";
    let checked = new Set();
    // Раскрытые вручную узлы (kindNodeKey/areaNodeKey) — по умолчанию всё свёрнуто.
    let expanded = new Set();
    // Продукт (ряд «Что», по умолчанию «Всё») и вид (ряд «Как», по умолчанию
    // не выбран) — только для сортировки/раскрытия/подсветки кнопок и пометки
    // «маркер: smoke» в строке итога; какие файлы отмечены — решает
    // presetLeafTargets(data, {product, kind}).
    let product = "all";
    let kind = null;

    // Перед любым пересбором innerHTML (поиск/пресет/раскрытие) сначала снимаем
    // текущее состояние чекбоксов из DOM — иначе оно потеряется при замене разметки.
    function snapshotChecked() {
      checked = new Set(checkedFileTargets(box));
    }

    // Узлы, раскрытые вручную, плюс (пока есть непустой поисковый запрос) узлы,
    // в которых нашлось совпадение — второе не сохраняется в expanded, поэтому
    // при очистке поиска раскрытыми остаются только узлы из ручного клика.
    function effectiveExpandedKeys() {
      const keys = new Set(expanded);
      SectionsTreeLogic.expandedKeysForQuery(data, query).forEach((k) => keys.add(k));
      return keys;
    }

    function updateProductButtons() {
      if (!productsRow) return;
      productsRow.querySelectorAll(".sections-preset-btn[data-product]").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.product === product);
      });
    }

    function updateKindButtons() {
      if (!kindsRow) return;
      kindsRow.querySelectorAll(".sections-preset-btn[data-preset]").forEach((btn) => {
        const btnKind = btn.dataset.preset;
        btn.classList.toggle("active", btnKind === kind);
        btn.classList.toggle("dim", !SectionsTreeLogic.kindAvailableForProduct(btnKind, product));
      });
    }

    function updateSummaryLine() {
      if (!summaryLineEl) return;
      const counts = SectionsTreeLogic.countCheckedByKind(data, new Set(checkedFileTargets(box)));
      let line = `Выбрано: ${counts.total} ${pluralRu(counts.total, "тест", "теста", "тестов")} · API ${counts.api} · UI ${counts.ui} · E2E ${counts.e2e}`;
      // Читаем сам селект, а не kind — так строка верна и когда маркер
      // выставлен вручную из списка, без клика по кнопке (см. ниже
      // markerSelectEl.addEventListener("change", ...)).
      const marker = markerSelectEl ? markerSelectEl.value : "";
      if (marker) line += ` · маркер: ${marker}`;
      summaryLineEl.textContent = line;
    }

    function render() {
      const filtered = SectionsTreeLogic.filterSectionsTree(data, query);
      const sortedKinds = SectionsTreeLogic.sortKindsForPreset(filtered.kinds, kind);
      box.innerHTML = buildSectionsTreeHtml({ kinds: sortedKinds }, checked, effectiveExpandedKeys());
      syncAllAncestors(box);
      updateProductButtons();
      updateKindButtons();
      updateSummaryLine();
      if (onStateChange) onStateChange();
    }

    // Общий хвост клика по продукту/виду: пересчитать отмеченные файлы и
    // раскрытые узлы под новую пару (product, kind), перерисовать.
    function applyPresetChange() {
      // Пресет сбрасывает раскрытые узлы на «выбранный вид раскрыт, остальное
      // свёрнуто» ('all'/'smoke'/без вида ничего не раскрывают особо, см. mission).
      expanded = new Set(SectionsTreeLogic.expandedKeysForPreset(data.kinds, kind));
      if (markerSelectEl) {
        if (kind === "smoke") markerSelectEl.value = "smoke";
        // e2e — тоже маркер pytest (@pytest.mark.e2e в auto_tests_vshgu), но
        // псевдо-раздел tests/e2e уже содержит ровно эти тесты, включая
        // размеченные прямо в tests/ui/* (app.core.sections._e2e_virtual_files)
        // — presetLeafTargets отмечает только их, не всё дерево целиком, как
        // smoke. Маркер всё равно ставим — подстрахует, если в файле есть и
        // другие тесты.
        else if (kind === "e2e") markerSelectEl.value = "e2e";
      }
      checked = new Set(SectionsTreeLogic.presetLeafTargets(data, { product, kind }));
      render();
    }

    setupTreeEvents(box, {
      onHeaderToggle(key) {
        snapshotChecked();
        if (expanded.has(key)) expanded.delete(key); else expanded.add(key);
        render();
      },
      onLeafChange: updateSummaryLine,
    });
    if (searchInput) {
      searchInput.addEventListener("input", () => {
        snapshotChecked();
        query = searchInput.value;
        render();
      });
    }
    if (productsRow) {
      productsRow.addEventListener("click", (ev) => {
        const btn = ev.target.closest(".sections-preset-btn[data-product]");
        if (!btn) return;
        product = btn.dataset.product;
        // Вид, недоступный при новом продукте (Mobile вне LMS/Всё, Regression/
        // Integration на Helpdesk/LRS), сбрасываем — иначе кнопка «Как» осталась
        // бы подсвеченной и недоступной одновременно.
        if (kind && !SectionsTreeLogic.kindAvailableForProduct(kind, product)) kind = null;
        applyPresetChange();
      });
    }
    if (kindsRow) {
      kindsRow.addEventListener("click", (ev) => {
        const btn = ev.target.closest(".sections-preset-btn[data-preset]");
        if (!btn) return;
        const clicked = btn.dataset.preset;
        if (!mobile && clicked === "mobile") return;
        if (!SectionsTreeLogic.kindAvailableForProduct(clicked, product)) return;
        // Повторный клик по уже выбранному виду снимает его.
        kind = kind === clicked ? null : clicked;
        applyPresetChange();
      });
    }
    // Маркер можно выставить и вручную из списка, без клика по кнопке — кнопка,
    // соответствующая текущему значению (smoke/e2e), всё равно подсвечивается
    // (чисто визуально: активный чекбокс выбора файлов этим не трогаем).
    if (markerSelectEl) {
      markerSelectEl.addEventListener("change", () => {
        kind = markerSelectEl.value || null;
        updateProductButtons();
        updateKindButtons();
        updateSummaryLine();
        if (onStateChange) onStateChange();
      });
    }

    return {
      setData(newData) {
        data = newData;
        checked = new Set();
        expanded = new Set();
        product = "all";
        kind = null;
        updateProductCounts(productsRow, data);
        render();
      },
      // Предустановка отмеченных файлов извне (страница «Сборка», см. initBuildMode) —
      // тот же checked, что и после клика по пресету, дерево перерисовывается.
      setChecked(fileTargets) {
        checked = new Set(fileTargets);
        render();
      },
      targets() {
        return SectionsTreeLogic.collectTargets(data, new Set(checkedFileTargets(box)));
      },
      // Отмеченные файлы как есть, без схлопывания в папки (targets() выше) —
      // для счётчиков «N файлов · API x · UI y» в сводке свёрнутой формы.
      checkedFiles() {
        return checkedFileTargets(box);
      },
      // Текущая пара продукт/вид — для автометки сборки и чипа «Сборка: …»
      // (ui/project-run-window.js::updateBuildChip).
      getProductKind() {
        return { product, kind };
      },
    };
  }

  const sectionsPicker = createSectionsPicker(
    sectionsTreeBox, sectionsSearchInput, sectionsProductsRow, sectionsKindsRow, markerSelect, sectionsSummaryLine,
    { mobile: true, onStateChange: () => updateBuildChip() }
  );
  const schedSectionsPicker = createSectionsPicker(
    schedSectionsTreeBox, schedSectionsSearchInput, schedSectionsProductsRow, schedSectionsKindsRow, schedMarkerSelect, schedSectionsSummaryLine,
    { mobile: false }
  );

  let sectionsDataCache = { kinds: [] };

  async function loadSections() {
    try {
      const data = await api(`/api/projects/${encodeURIComponent(projectName)}/sections`);
      sectionsDataCache = data;
      sectionsPicker.setData(data);
      schedSectionsPicker.setData(data);
    } catch (err) {
      sectionsTreeBox.innerHTML = "";
      schedSectionsTreeBox.innerHTML = "";
      testsError.textContent = `Не удалось загрузить дерево разделов: ${err.message}`;
      testsError.hidden = false;
    }
  }

  // Ручное поле (под спойлером) заменяет собой выбор в дереве, когда заполнено —
  // см. подсказку в разметке (ui/project.html).
  function selectedTarget() {
    const manual = manualTargetInput.value.trim();
    if (manual) return manual;
    return sectionsPicker.targets().join("\n");
  }

  function currentTargetLines() {
    const manual = manualTargetInput.value.trim();
    if (manual) return manual.split("\n").map((l) => l.trim()).filter(Boolean);
    return sectionsPicker.targets();
  }

  // target -> tests_count по уже загруженному дереву разделов (GET .../sections) —
  // тот же источник, что у BuildPageLogic.totalTestsCount, только по отдельным файлам,
  // а не по разделу целиком (см. RunLiveLogic.countTargetTests).
  // Карта tests_count по target'у на ВСЕХ уровнях дерева, не только по файлам:
  // SectionsTreeLogic.collectTargets схлопывает полностью отмеченный раздел/область
  // в их путь папки ("tests/api"/"tests/api/notifications") — без kindNode.target
  // и area.target в этой карте такие схлопнутые цели не находились бы и считались
  // бы как «1 тест» в RunLiveLogic.countTargetTests (использует this же map),
  // занижая подсказку «Эфир» для любого пресета, выбирающего раздел/область
  // целиком (API/UI/E2E/Всё/Regression/Mobile — не только файлами поодиночке).
  function testsCountByTarget() {
    const map = {};
    (sectionsDataCache.kinds || []).forEach((k) => {
      let kindTotal = 0;
      (k.areas || []).forEach((a) => {
        let areaTotal = 0;
        (a.files || []).forEach((f) => {
          map[f.target] = f.tests_count;
          areaTotal += f.tests_count;
        });
        if (a.target) map[a.target] = areaTotal;
        kindTotal += areaTotal;
      });
      if (k.target) map[k.target] = kindTotal;
    });
    return map;
  }

  // Галочка «Эфир» (docs/missions/2026-10-01_live_stream.md, «Уточнение владельца
  // 01.10») — доступность и подсказка пересчитываются при любом изменении выбора
  // тестов (дерево разделов, пресеты, ручной ввод), до отправки прогона.
  function updateLiveCheckboxState() {
    const count = RunLiveLogic.countTargetTests(currentTargetLines(), testsCountByTarget());
    const state = RunLiveLogic.liveCheckboxState(count, liveMaxTests);
    liveCheckbox.disabled = state.disabled;
    if (state.disabled) liveCheckbox.checked = false;
    liveCheckboxHint.hidden = !state.hint;
    liveCheckboxHint.textContent = state.hint;
    liveCheckboxHint.classList.toggle("limit-exceeded", state.disabled);
    updateMarkerConflictHint();
  }

  // Предупреждение «маркер × цели» (SectionsTreeLogic.markerConflict): маркер
  // отфильтрует все выбранные файлы и прогон соберёт 0 тестов. Пересчитывается
  // вместе с подсказкой «Эфир» — на любое изменение выбора (см. updateLiveCheckboxState)
  // и отдельно на смену маркера. Только предупреждение, запуск не блокируем:
  // для api/ui проверка по папке — эвристика, для smoke не вычисляется вовсе.
  function updateMarkerConflictHint() {
    const marker = markerSelect.value;
    const conflict = SectionsTreeLogic.markerConflict(sectionsDataCache, marker, currentTargetLines());
    if (!conflict) {
      markerConflictHint.hidden = true;
      return;
    }
    markerConflictHint.innerHTML = `
      <span>⚠ Маркер <b>${escapeHtml(marker)}</b> не стоит ни на одном из выбранных тестов — прогон соберёт <b>0 тестов</b> (как #89).</span>
      <button type="button" id="marker-conflict-clear-btn">Снять маркер</button>
    `;
    markerConflictHint.hidden = false;
  }

  markerSelect.addEventListener("change", updateMarkerConflictHint);
  markerConflictHint.addEventListener("click", (ev) => {
    if (!ev.target.closest("#marker-conflict-clear-btn")) return;
    markerSelect.value = "";
    // штатный change — чтобы пикер снял подсветку кнопки пресета и обновил строку итога
    markerSelect.dispatchEvent(new Event("change"));
  });

  manualTargetInput.addEventListener("input", updateLiveCheckboxState);
  sectionsTreeBox.addEventListener("change", (ev) => {
    if (ev.target.matches("input.tree-check")) updateLiveCheckboxState();
  });
  sectionsProductsRow.addEventListener("click", (ev) => {
    if (!ev.target.closest(".sections-preset-btn[data-product]")) return;
    updateLiveCheckboxState();
  });
  sectionsKindsRow.addEventListener("click", (ev) => {
    const presetBtn = ev.target.closest(".sections-preset-btn[data-preset]");
    if (!presetBtn) return;
    // Пресет «Mobile» сам включает вёрстку Pixel 7 — без неё выбранные им
    // tests/ui/mobile/* гоняются в обычном десктопном viewport, что бессмысленно.
    if (presetBtn.dataset.preset === "mobile" && !mobileCheckbox.checked) {
      mobileCheckbox.checked = true;
      mobileCheckbox.dispatchEvent(new Event("change"));
    }
    updateLiveCheckboxState();
  });

  // Галочка «Мобильный» (docs/missions/2026-10-06_mobile_frame.md, п.2) включает
  // «Эфир» автоматически, но не блокирует её ручное выключение после этого.
  mobileCheckbox.addEventListener("change", () => {
    if (mobileCheckbox.checked) liveCheckbox.checked = true;
    updateBuildChip();
  });

