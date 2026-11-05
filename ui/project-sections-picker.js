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

  // Строка вида tests/<kind> (docs/missions/2026-11-03_area_chips.md, раздел 1) —
  // число тестов раздела целиком и число отмеченных тестов (не файлов, как в
  // countText() выше — макет считает именно тесты). Внутри одного kindNode области
  // не пересекаются, поэтому простая сумма area.tests_count не нуждается в дедупе
  // (дедуп нужен только между kind, см. SectionsTreeLogic.fileTestCounts/countCheckedByKind).
  function kindTestsTotal(kindNode) {
    return (kindNode.areas || []).reduce((sum, area) => sum + (area.tests_count || 0), 0);
  }

  function kindTestsSelected(kindNode, checkedTargets) {
    return SectionsTreeLogic.kindAllFiles(kindNode).reduce(
      (sum, file) => sum + (checkedTargets.has(file.target) ? (file.tests_count || 0) : 0),
      0
    );
  }

  // Строка вида (макет, блок .tkind): чекбокс-тристейт (SectionsTreeLogic.kindState)
  // вместо обычного input — клик по нему переключает все файлы вида (toggleKind),
  // поэтому это кнопка, а не чекбокс-инпут (см. createSectionsPicker/setupTreeEvents).
  function kindRowHtml(kindNode, checkedTargets, open) {
    const state = SectionsTreeLogic.kindState(kindNode, checkedTargets);
    const cbClass = state === "on" ? "on" : state === "partial" ? "part" : "";
    const cbMark = state === "on" ? "✓" : state === "partial" ? "–" : "";
    const label = KIND_LABELS[kindNode.kind] || kindNode.kind;
    const total = kindTestsTotal(kindNode);
    const selected = kindTestsSelected(kindNode, checkedTargets);
    return `
      <div class="tree-node-head tkind-row" role="button" tabindex="0" aria-expanded="${open ? "true" : "false"}">
        <span class="tree-chev" aria-hidden="true">▸</span>
        <button type="button" class="tkind-cb ${cbClass}" data-kind="${escapeHtml(kindNode.kind)}" role="checkbox" aria-checked="${state === "on" ? "true" : state === "partial" ? "mixed" : "false"}" aria-label="Выбрать ${escapeHtml(label)} целиком">${cbMark}</button>
        <span class="tkind-label">${escapeHtml(label)}</span>
        <span class="tkind-meta">${total} тест. · выбрано ${selected}</span>
      </div>
    `;
  }

  // Плашки областей под строкой вида (макет, блок .areas/.area.on|.off, partial —
  // своё правило из плана, в макете его нет): для tests/e2e без области (area.area
  // == null) — одна плашка "e2e" на весь раздел. anySelected — выбрано хоть что-то
  // в ЦЕЛОЙ форме (не только в этом kind) — "off" тускнеет только тогда, иначе
  // (ничего вообще не выбрано) все плашки выглядят одинаково нейтрально.
  function areaChipsHtml(kindNode, checkedTargets, anySelected) {
    return kindNode.areas.map((area) => {
      const state = SectionsTreeLogic.areaState(area, checkedTargets);
      const label = area.area == null ? "e2e" : SectionsTreeLogic.areaLabel(area.area);
      const cls = ["area-chip"];
      if (state === "on") cls.push("on");
      else if (state === "partial") cls.push("partial");
      else if (anySelected) cls.push("off");
      return `<button type="button" class="${cls.join(" ")}" data-kind="${escapeHtml(kindNode.kind)}" data-area="${area.area == null ? "" : escapeHtml(area.area)}" title="${escapeHtml(area.section || area.area || label)}">${escapeHtml(label)} ${area.tests_count}</button>`;
    }).join("");
  }

  // Раскрытые узлы (expandedKeys — Set из SectionsTreeLogic.kindNodeKey/areaNodeKey,
  // уже объединяет ручные клики и авто-раскрытие по поиску, см. createSectionsPicker)
  // переживают пересборку innerHTML — ключ раскрытия хранится вне разметки.
  function buildSectionsTreeHtml(filtered, checkedTargets, expandedKeys) {
    if (!filtered.kinds.length) return `<p class="muted">Разделы не найдены.</p>`;
    const anySelected = checkedTargets.size > 0;
    return filtered.kinds.map((kindNode) => {
      const kindKey = SectionsTreeLogic.kindNodeKey(kindNode);
      const kindOpen = expandedKeys.has(kindKey);

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

      return `
        <div class="tree-file${kindOpen ? " open" : ""}" data-tree-key="${escapeHtml(kindKey)}">
          ${kindRowHtml(kindNode, checkedTargets, kindOpen)}
          <div class="areas-row">${areaChipsHtml(kindNode, checkedTargets, anySelected)}</div>
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

  // После полной пересборки innerHTML (рендер дерева заново — поиск/пресет/раскрытие)
  // родительский чекбокс области рендерится как ни на что не похожий на состояние
  // листьев — buildSectionsTreeHtml знает только про checked-атрибут самих файлов
  // (счётчик «выбрано N из M» он, в отличие от checked/indeterminate, уже посчитал
  // сам). Эта функция досчитывает checked/indeterminate у всех .tree-class по уже
  // отрисованным листьям (у строки вида над плашками, .tkind-row, своего
  // input.tree-check больше нет — её тристейт (kindState) и так целиком посчитан
  // в kindRowHtml на каждый рендер, досчитывать по DOM нечего).
  function syncAllAncestors(box) {
    box.querySelectorAll("div.tree-class").forEach((classScope) => {
      setParentState(
        classScope.querySelector(":scope > .tree-node-head > input.tree-check"),
        classScope.querySelectorAll(".tree-tests input.tree-leaf")
      );
    });
  }

  // handlers.onHeaderToggle(key) — клик/Enter/Space по заголовку узла (не по
  // чекбоксу — ev.target.matches("input.tree-check") возвращает раньше, поэтому
  // ниже не нужен preventDefault/stopImmediatePropagation, чекбокс и раскрытие
  // не конфликтуют). handlers.onKindCheckboxToggle(rawKind)/onAreaChipToggle(rawKind,
  // rawArea) — клик по новой строке вида/плашке области (кнопки .tkind-cb/.area-chip,
  // не input, поэтому разбираются раньше общего .tree-node-head-тоггла раскрытия).
  // handlers.onLeafChange() — любое ручное изменение листа в развёрнутом дереве
  // точечного выбора: полный рендер (а не точечный DOM-патч) — проще и надёжнее,
  // раз строка вида/плашки всё равно требуют пересчёта по всему checked.
  function setupTreeEvents(box, handlers) {
    const onHeaderToggle = (handlers && handlers.onHeaderToggle) || null;
    const onLeafChange = (handlers && handlers.onLeafChange) || null;
    const onKindCheckboxToggle = (handlers && handlers.onKindCheckboxToggle) || null;
    const onAreaChipToggle = (handlers && handlers.onAreaChipToggle) || null;
    const toggleFromEvent = (ev) => {
      const kindCb = ev.target.closest(".tkind-cb");
      if (kindCb) { if (onKindCheckboxToggle) onKindCheckboxToggle(kindCb.dataset.kind); return; }
      const chip = ev.target.closest(".area-chip");
      if (chip) { if (onAreaChipToggle) onAreaChipToggle(chip.dataset.kind, chip.dataset.area); return; }
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
        const scope = checkbox.closest("div.tree-class");
        scope.querySelectorAll("input.tree-check").forEach((cb) => {
          if (cb !== checkbox) { cb.checked = checkbox.checked; cb.indeterminate = false; }
        });
      }
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

  // Ряд «Что» (LMS/Helpdesk/LRS/Всё) — бизнес-термины конкретно ВШГУ
  // (SectionsTreeLogic.hasNamedProducts), на проекте без таких разделов
  // (bike_fit, Velo_bot, Courseditor_Learn, Experts) прячем его целиком вместе
  // с подписью «Что», а не показываем «Helpdesk 0»/«LRS 0» без единого теста
  // под ними. Кнопка «Integration» в ряду «Как» — то же: без этих разделов она
  // всегда выбирала бы пустой набор, так что прячем и её. «Regression»/«Mobile»
  // остаются — это общие для любого проекта понятия (маркер pytest/раздел
  // tests/ui/mobile), просто могут не дать файлов на конкретном дереве, как и
  // «API»/«UI»/«E2E» на проекте без соответствующей папки.
  function updateProductRowVisibility(productsRow, kindsRow, data) {
    const named = SectionsTreeLogic.hasNamedProducts(data);
    if (productsRow) {
      const group = productsRow.closest(".preset-group") || productsRow;
      group.hidden = !named;
    }
    if (kindsRow) {
      const integrationBtn = kindsRow.querySelector('[data-preset="integration"]');
      if (integrationBtn) integrationBtn.hidden = !named;
    }
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

    // kindNode по kindNode.kind (как в data-kind у .tkind-cb/.area-chip) — для
    // toggleKind/toggleArea по клику (см. setupTreeEvents ниже).
    function findKindNode(rawKind) {
      return (data.kinds || []).find((k) => k.kind === rawKind) || null;
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
      // Ручное изменение листа в развёрнутом дереве точечного выбора: полный
      // рендер, не точечный DOM-патч — строка вида и плашки областей всё равно
      // пересчитываются по всему checked (areaState/kindState), в отличие от
      // старого countText() выше это им не обойти.
      onLeafChange() {
        snapshotChecked();
        render();
      },
      onKindCheckboxToggle(rawKind) {
        const kindNode = findKindNode(rawKind);
        if (!kindNode) return;
        snapshotChecked();
        checked = SectionsTreeLogic.toggleKind(kindNode, checked);
        render();
      },
      onAreaChipToggle(rawKind, rawArea) {
        const kindNode = findKindNode(rawKind);
        const area = kindNode && kindNode.areas.find((a) => (a.area == null ? "" : a.area) === rawArea);
        if (!area) return;
        snapshotChecked();
        checked = SectionsTreeLogic.toggleArea(area, checked);
        render();
      },
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
        updateProductRowVisibility(productsRow, kindsRow, data);
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
    {
      mobile: true,
      // Клик по новой строке вида/плашке области (toggleKind/toggleArea) меняет
      // checked и перерисовывает дерево так же, как клик по чекбоксу файла или
      // пресет — но, в отличие от них, не идёт через "change"/отдельные
      // слушатели на sectionsProductsRow/sectionsKindsRow (см. ниже), поэтому
      // «Эфир»/маркер-конфликт пересчитываем здесь же, на каждый рендер.
      onStateChange: () => { updateBuildChip(); updateLiveCheckboxState(); },
    }
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

