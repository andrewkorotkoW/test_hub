---
version: "alpha"
name: "test_hub"
description: "Дизайн-система test_hub — панели прогонов автотестов ВШГУ: тёмная и светлая темы, палитра статусов, цвет проекта"
colors:
  # поверхности — тёмная тема (по умолчанию внутри проекта)
  bg: "#0f1223"
  bgSidebar: "#151a2e"
  surface: "#1b2036"
  surfaceHover: "#232945"
  border: "#262c47"
  text: "#e7e9f5"
  textMuted: "#9298b8"
  # поверхности — светлая тема (стартовая страница и список проектов по умолчанию)
  bgLight: "#f5f6f8"
  bgSidebarLight: "#ffffff"
  surfaceLight: "#ffffff"
  surfaceHoverLight: "#f3f4f6"
  borderLight: "#e1e4e9"
  textLight: "#1f2430"
  textMutedLight: "#6b7280"
  # акцент (по умолчанию; у проекта может быть свой из палитры projectAccents)
  accent: "#2563eb"
  accentHover: "#1d4ed8"
  accentText: "#ffffff"
  danger: "#dc2626"
  dangerHover: "#b91c1c"
  # статусы прогонов и тестов — семантика, палитрой проекта НЕ меняются
  passed: "#22c55e"
  failed: "#ff4d6d"
  broken: "#f59e0b"
  skipped: "#8b93a7"
  xfail: "#f5b642"
  flaky: "#a78bfa"
  running: "#2563eb"
  queued: "#64748b"
  cancelled: "#6b7280"
  unknown: "#9333ea"
  # градиент графиков
  gradientStart: "#7c5cff"
  gradientMid: "#ff4fa3"
  gradientEnd: "#38d6ff"
projectAccents:
  - "#2563eb"
  - "#7c5cff"
  - "#ff4fa3"
  - "#38d6ff"
  - "#22c55e"
  - "#f59e0b"
  - "#ff4d6d"
  - "#14b8a6"
  - "#8b93a7"
typography:
  fontFamily: "Golos Text, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
  fontFamilyMono: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
  h1:
    fontSize: 22px
    fontWeight: 700
  h2:
    fontSize: 18px
    fontWeight: 700
  kpi:
    fontSize: 26px
    fontWeight: 700
    fontFamily: "{typography.fontFamilyMono}"
  body:
    fontSize: 14px
    lineHeight: 1.45
  small:
    fontSize: 12px
  label:
    fontSize: 11px
    letterSpacing: 0.06em
    textTransform: uppercase
    fontWeight: 600
  code:
    fontSize: 12px
    fontFamily: "{typography.fontFamilyMono}"
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 22px
  xxl: 28px
rounded:
  sm: 6px
  md: 8px
  lg: 10px
  card: 16px
  pill: 999px
elevation:
  card: "0 8px 24px rgba(0, 0, 0, .35)"
  cardLight: "0 1px 3px rgba(15, 23, 42, .08)"
  glow: "0 0 0 1px {colors.accent}, 0 0 16px {colors.accent}"
components:
  card:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.border}"
    rounded: "{rounded.card}"
    padding: "{spacing.lg} 18px"
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accentText}"
    rounded: "{rounded.md}"
    padding: "9px 14px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.border}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
  status-pill:
    rounded: "{rounded.pill}"
    fontSize: "{typography.small.fontSize}"
    fontWeight: 600
    padding: "3px 9px"
  sidebar-item-active:
    backgroundColor: "color-mix(in srgb, {colors.accent} 16%, transparent)"
    textColor: "{colors.text}"
  table-header:
    fontSize: "{typography.label.fontSize}"
    textColor: "{colors.textMuted}"
  input:
    backgroundColor: "{colors.surfaceHover}"
    borderColor: "{colors.border}"
    rounded: "{rounded.lg}"
---

## Overview

test_hub — рабочий инструмент QA: панели прогонов автотестов, покрытие, xfail, расписания.
Язык интерфейса «аналитический дашборд»: карточки на тёмном сине-фиолетовом фоне, неоновые
градиенты только в графиках, всё остальное спокойное. Интерфейс сканируют, а не читают: сначала
сводка (KPI, кольцо статусов), потом детали (таблицы, лента). Состояние кодируется цветом и формой
(пилюля, точка, полоса), не только числом. Все подписи на русском.

Референсы владельца лежат в `docs/missions/REFERENCES.md` и `docs/missions/redesign/`
(четыре варианта страницы проекта, `variants/mockups.html` — живой макет с этими же токенами).

## Colors

- **Две темы.** Тёмная — по умолчанию внутри проекта; светлая — по умолчанию на стартовой странице
  и списке проектов. Выбор пользователя хранится в `localStorage` и применяется ко всем страницам;
  тема проставляется до первой отрисовки, без вспышки. Токены светлой темы — суффикс `Light`.
- **Акцент проекта.** У каждого проекта свой акцентный цвет из `projectAccents` (хранится в БД,
  колонка `color`). Он красит кнопки, ссылки, активный пункт сайдбара, обводку KPI и основной цвет
  графиков (градиент строится от него). Контраст текста на кнопке: тёмный текст на светлых
  акцентах (#38d6ff, #22c55e, #f5b642), белый на остальных.
- **Статусы — семантика, не бренд.** passed / failed / broken / skipped / xfail / flaky / running
  всегда из токенов статусов и никогда не перекрашиваются палитрой проекта. Зелёный = только
  passed, красный = только failed/danger, жёлтый = xfail/broken, фиолетовый = flaky.
- **Нейтрали с холодным сине-фиолетовым сдвигом**, чистый серый не использовать.
- Градиент `gradientStart → gradientMid → gradientEnd` — только для площадных и линейных графиков
  и одной тонкой полосы-акцента (например, верх карточки «последний прогон»). Не для текста и кнопок.

## Typography

- Основной шрифт Golos Text (кириллица, Google Fonts), моноширинный JetBrains Mono — для чисел,
  идентификаторов прогонов, дат, кода. Все числа в таблицах — `font-variant-numeric: tabular-nums`.
- Шкала: h1 22, h2 18, KPI 26 (моно, жирный), body 14, small 12, label 11 (капс, разрядка 0.06em).
  Мельче 11px не бывает.
- Заголовки карточек — `label` цветом `textMuted`; значение KPI — единственный крупный элемент карточки.

## Layout

- Каркас: сайдбар 220px (лого, разделы, переключатель темы внизу) + контент до 1280px.
  Мобильная вёрстка ≤768px: сайдбар скрыт, сетки в одну колонку, таблицы прокручиваются внутри
  своего контейнера (`overflow-x: auto`), страница никогда не скроллится по горизонтали.
- Сетки: KPI — 6 колонок, «кольцо + столбцы» — 300px + остаток, «лента + xfail» — остаток + 340px.
  Отступы между карточками 12–16px, внутри карточки 16px 18px.
- Порядок на странице проекта: заголовок с точкой цвета проекта и статусом текущего прогона →
  KPI → графики → лента прогонов и дефекты.

## Elevation & Depth

- Один уровень поверхности над фоном: карточка с тонкой границей `border` и тенью `elevation.card`
  (в светлой теме `cardLight`). Вложенных карточек нет.
- Свечение (`elevation.glow`) — только для состояний «требует внимания» (например, кнопка со свежей
  сводкой), не для декора.

## Shapes

- Карточки 16px, кнопки и поля 8–10px, пилюли статусов 999px, мини-бары 3px.
- Точка цвета проекта — круг 14px с обводкой цвета поверхности.

## Components

- **Пилюля статуса**: цвет текста = цвет статуса, фон = тот же цвет на 14–16% (`color-mix`),
  слева точка 7px того же цвета. Текст: «идёт», «упал», «успешно», «в очереди», «отменён».
- **KPI-карточка**: подпись (label) → значение (моно 26) → дельта к прошлому прогону строкой 12px,
  зелёная вверх, красная вниз.
- **Кольцо статусов**: сегменты passed/failed/skipped, в центре процент passed (моно, жирный)
  и подпись «passed из завершённых».
- **Столбцы по прогонам**: passed зелёный и failed красный парами, подписи `#id цель`, сетка
  тонкими линиями `border`.
- **Лента прогонов**: `#id` моно, стенд, цель, пилюля статуса, полоса passed/failed/skipped
  шириной 120px, дата моно цветом `textMuted`.
- **Таблицы**: заголовки label цветом `textMuted`, строки разделены `border` на 60% прозрачности,
  ховер — `surfaceHover`.
- **Переключатель темы**: кнопка с рамкой `border`, подпись «Тема: тёмная/светлая».

## Do's and Don'ts

- Делать: брать цвета только из токенов; кодировать статус пилюлей/точкой, а не текстом;
  проверять контраст в обеих темах; уважать `prefers-reduced-motion` (пульсация выключается,
  статичное свечение остаётся); все подписи на русском.
- Не делать: не перекрашивать статусы палитрой проекта; не использовать градиент в тексте и
  кнопках; не ставить эмодзи вместо иконок в UI; не делать «вспышку» тёмного фона на светлой
  странице; не заводить второй набор цветов в JS — только CSS-переменные из `ui/style.css`.
- Исторические значения в `ui/style.css` (passed #16a34a, failed #dc2626, broken #d97706 и т.п.)
  при следующей правке привести к токенам этого файла; `tm-*` цвета treemap — к тем же статусам.
