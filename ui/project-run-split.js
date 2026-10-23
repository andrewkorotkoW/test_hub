/*
 * project.html, вкладка «Запуск»: карточка прогона «Сплит» — утилиты рамки
 * вокруг кадра эфира/видео теста (isPhoneFrameOff/setPhoneFrameOff/
 * phoneFrameDevice/setPhoneFrameDevice/maybePhoneFrame/applyPhoneFrameSizing/
 * frameTimeText), выбор телефон/планшет (RunLiveLogic.frameDimensions) —
 * визуальный, эмуляция теста всегда Pixel 7 — и состояние отчёта текущего
 * прогона (currentTests/currentWs/sawLine), используемое ui/project-run-window.js.
 * Тот же приём рамки, что и в ui/share.js (общие ключи localStorage), — здесь
 * своя копия, не модуль.
 */

  let currentTests = [];
  let currentWs = null;
  let sawLine = false;

  // ---------------- карточка прогона · вариант «Сплит» (docs/missions/redesign/run_window) ----------------
  // Слева список тестов прогона (GET/WS test_start/test_end), справа окно выбранного теста
  // с вкладками Кадры/Консоль/Запросы; старые прогоны без разметки по nodeid показывают
  // только «Весь лог» — см. applyViewMode().
  let splitTests = [];
  let splitTestsByNodeid = {};
  let selectedNodeid = null;
  let selectedTestLog = [];
  let selectedTestFrames = [];
  let activeWindowTab = "console";
  let hasMarkup = false;
  let viewMode = "split";
  let runSentryData = null;
  // Завершённость прогона (docs/missions/2026-10-13_run_compare_and_causes.md) —
  // отдельно от hasMarkup: «Сравнить с…»/«Причины» имеют смысл только для
  // passed/failed/cancelled, независимо от того, есть ли у прогона разметка по
  // nodeid (старые прогоны без разметки всё равно можно сравнивать по allure).
  const FINISHED_STATUSES = ["passed", "failed", "cancelled"];
  let isFinished = false;
  // «Эфир»/«Видео» (docs/missions/2026-10-01_live_stream.md) — liveFrame держит только
  // последний кадр прогона (сервер тоже хранит один на run_id, см. app/core/live.py),
  // followEnabled — «Следить за прогоном», выключается кликом по тесту вручную (см.
  // клик-хендлер run-tests-rail ниже) и снова включается чекбоксом run-follow-checkbox.
  let liveFrame = null; // { nodeid, step, jpegB64, receivedAt, ts }
  let followEnabled = true;
  // «Эфир»/«Следить за прогоном» — только у прогонов с live=true (docs/missions/
  // 2026-10-01_live_stream.md, «Уточнение владельца 01.10»); отдаётся в GET .../report.
  let currentRunLive = false;
  // Рамка телефона (docs/missions/2026-10-06_mobile_frame.md, п.3-4) — отдаётся тем же
  // payload-полем mobile, что и live.
  let currentRunMobile = false;

  const PHONE_FRAME_OFF_KEY = "th_phone_frame_off";
  function isPhoneFrameOff() {
    try { return localStorage.getItem(PHONE_FRAME_OFF_KEY) === "1"; } catch { return false; }
  }
  function setPhoneFrameOff(off) {
    try { localStorage.setItem(PHONE_FRAME_OFF_KEY, off ? "1" : "0"); } catch { /* localStorage недоступен */ }
  }

  // Выбор рамки просмотра — телефон/планшет (RunLiveLogic.frameDimensions), чисто
  // визуальный: сам тест по-прежнему шёл с эмуляцией Pixel 7 независимо от выбора.
  const PHONE_FRAME_DEVICE_KEY = "th_phone_frame_device";
  function phoneFrameDevice() {
    try { return localStorage.getItem(PHONE_FRAME_DEVICE_KEY) === "tablet" ? "tablet" : "phone"; } catch { return "phone"; }
  }
  function setPhoneFrameDevice(device) {
    try { localStorage.setItem(PHONE_FRAME_DEVICE_KEY, device === "tablet" ? "tablet" : "phone"); } catch { /* localStorage недоступен */ }
  }

  // Оборачивает готовую разметку кадра эфира/видео в рамку (телефон/планшет, выбор
  // переключателем) у прогонов с run.mobile; переключатель «Без рамки» всегда рядом
  // (можно выключить рамку и включить обратно), desktop-прогоны (currentRunMobile=false)
  // — без изменений (п.3 миссии).
  function maybePhoneFrame(innerHtml, timeText) {
    if (!currentRunMobile) return innerHtml;
    const off = isPhoneFrameOff();
    const device = phoneFrameDevice();
    const toggleRow = `
      <div class="phone-frame-toggle-row">
        <div class="phone-frame-device-switch" role="group" aria-label="Рамка просмотра">
          <button type="button" class="phone-frame-device-btn${device === "phone" ? " active" : ""}" data-device="phone">Телефон</button>
          <button type="button" class="phone-frame-device-btn${device === "tablet" ? " active" : ""}" data-device="tablet">Планшет</button>
        </div>
        <button type="button" class="phone-frame-toggle-btn">${off ? "Показать рамку" : "Без рамки"}</button>
      </div>`;
    if (!RunLiveLogic.phoneFrameEnabled(currentRunMobile, off)) return toggleRow + innerHtml;
    const dims = RunLiveLogic.frameDimensions(device);
    return `${toggleRow}
      <div class="phone-frame-wrap">
        <div class="${dims.className}">
          <div class="phone-frame-statusbar">${escapeHtml(timeText || "")}</div>
          <div class="phone-frame-screen">${innerHtml}</div>
        </div>
      </div>`;
  }

  // После вставки разметки — применяет масштаб (RunLiveLogic.phoneFrameScale) по
  // высоте уже отрендеренной панели и навешивает клики на переключатели «Без рамки»
  // и «Телефон»/«Планшет».
  function applyPhoneFrameSizing() {
    const frame = runWindowBody.querySelector(".phone-frame, .tablet-frame");
    if (frame) {
      const dims = RunLiveLogic.frameDimensions(phoneFrameDevice());
      const panelHeight = runWindowBody.clientHeight || 480;
      const scale = RunLiveLogic.phoneFrameScale(panelHeight, dims.height);
      frame.style.height = `${dims.height * scale}px`;
    }
    const toggleBtn = runWindowBody.querySelector(".phone-frame-toggle-btn");
    if (toggleBtn) {
      toggleBtn.addEventListener("click", () => {
        setPhoneFrameOff(!isPhoneFrameOff());
        renderWindowBody();
      });
    }
    runWindowBody.querySelectorAll(".phone-frame-device-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        setPhoneFrameDevice(btn.dataset.device);
        renderWindowBody();
      });
    });
  }

  function frameTimeText(frame) {
    if (!frame || frame.ts == null) return "";
    return new Date(frame.ts * 1000).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  }

