/*
 * Юнит-тесты чистой логики блока Sentry (ui/sentry-logic.js: sentrySignalClass —
 * пороги светофора, sentryIssueRowHtml — рендер строки issue для карточки
 * дашборда и вкладки окна прогона; project.js подключает этот файл и использует
 * window.SentryLogic).
 *
 * sentryIssueRowHtml зовёт escapeHtml (ui/common.js) как свободную глобальную
 * переменную (в браузере её даёт common.js, подключённый раньше) — здесь кладём
 * её в node-global тем же приёмом, что и раньше: вырезаем регуляркой из common.js
 * (единственное, что по-прежнему не модуль) и заменяем `??` на `||`, которого нет
 * в установленном здесь node 12 (см. testhub-redesign-ui-smoke-tests в памяти
 * агента) — для всех значений, которые реально передаются в escapeHtml
 * (issue.level/title/permalink — строки или undefined), `??` и `||` эквивалентны.
 */
"use strict";

var assert = require("assert");
var path = require("path");
var fs = require("fs");
var vm = require("vm");

var COMMON_JS_PATH = path.join(__dirname, "..", "..", "ui", "common.js");
var commonSrc = fs.readFileSync(COMMON_JS_PATH, "utf8");

var escapeHtmlMatch = commonSrc.match(/function escapeHtml\(value\) \{[\s\S]*?\n\}/);
if (!escapeHtmlMatch) throw new Error("не найдено в ui/common.js: escapeHtml");
var escapeHtmlSrc = escapeHtmlMatch[0].replace(/\?\?/g, "||");
vm.runInThisContext(escapeHtmlSrc + "\nglobal.escapeHtml = escapeHtml;", { filename: "common.js#escapeHtml" });

var SentryLogic = require(path.join(__dirname, "..", "..", "ui", "sentry-logic.js"));
var sentrySignalClass = SentryLogic.sentrySignalClass;
var sentryIssueRowHtml = SentryLogic.sentryIssueRowHtml;

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

// ------------------------------------------------------------------ sentrySignalClass

test("sentrySignalClass: 0 -> зелёный", function () {
  assert.strictEqual(sentrySignalClass(0), "sentry-signal-green");
});

test("sentrySignalClass: 1 -> жёлтый (нижняя граница)", function () {
  assert.strictEqual(sentrySignalClass(1), "sentry-signal-yellow");
});

test("sentrySignalClass: 4 -> жёлтый (верхняя граница)", function () {
  assert.strictEqual(sentrySignalClass(4), "sentry-signal-yellow");
});

test("sentrySignalClass: 5 -> красный (нижняя граница)", function () {
  assert.strictEqual(sentrySignalClass(5), "sentry-signal-red");
});

test("sentrySignalClass: большое число -> красный", function () {
  assert.strictEqual(sentrySignalClass(42), "sentry-signal-red");
});

// ------------------------------------------------------------------ sentryIssueRowHtml

function baseIssue(overrides) {
  return Object.assign(
    {
      id: "1",
      title: "NullPointerException in checkout",
      level: "error",
      count: 3,
      user_count: 2,
      first_seen: "2026-09-29T10:00:00Z",
      last_seen: "2026-09-29T10:05:00Z",
      permalink: "https://sentry.example.ru/issues/1/",
      is_new: false,
    },
    overrides || {}
  );
}

test("sentryIssueRowHtml: с permalink рендерится как <a>", function () {
  var html = sentryIssueRowHtml(baseIssue());
  assert.ok(html.indexOf("<a class=") === 0, "должен начинаться с <a>");
  assert.ok(html.indexOf('href="https://sentry.example.ru/issues/1/"') !== -1);
  assert.ok(html.indexOf('target="_blank"') !== -1);
});

test("sentryIssueRowHtml: без permalink рендерится как <div>, не <a>", function () {
  var html = sentryIssueRowHtml(baseIssue({ permalink: null }));
  assert.ok(html.indexOf("<a ") === -1, "не должно быть ссылки без permalink");
  assert.ok(html.indexOf("<div class=") === 0);
});

test("sentryIssueRowHtml: withNewBadge=false не показывает бейдж, даже если is_new=true", function () {
  var html = sentryIssueRowHtml(baseIssue({ is_new: true }), { withNewBadge: false });
  assert.ok(html.indexOf("sentry-new-badge") === -1);
  assert.ok(html.indexOf("is-new") === -1);
});

test("sentryIssueRowHtml: withNewBadge=true и is_new=true показывает бейдж и класс is-new", function () {
  var html = sentryIssueRowHtml(baseIssue({ is_new: true }), { withNewBadge: true });
  assert.ok(html.indexOf("sentry-new-badge") !== -1);
  assert.ok(html.indexOf("is-new") !== -1);
});

test("sentryIssueRowHtml: withNewBadge=true, но is_new=false -> бейджа нет", function () {
  var html = sentryIssueRowHtml(baseIssue({ is_new: false }), { withNewBadge: true });
  assert.ok(html.indexOf("sentry-new-badge") === -1);
});

test("sentryIssueRowHtml: withNewBadge по умолчанию false (без второго аргумента)", function () {
  var html = sentryIssueRowHtml(baseIssue({ is_new: true }));
  assert.ok(html.indexOf("sentry-new-badge") === -1);
});

test("sentryIssueRowHtml: count выводится как ×N", function () {
  var html = sentryIssueRowHtml(baseIssue({ count: 17 }));
  assert.ok(html.indexOf("×17") !== -1);
});

test("sentryIssueRowHtml: level и title экранируются от HTML-инъекции", function () {
  var html = sentryIssueRowHtml(
    baseIssue({ level: "<script>", title: '<img src=x onerror="alert(1)">' })
  );
  assert.ok(html.indexOf("<script>") === -1, "level не должен попадать в разметку сырым");
  assert.ok(html.indexOf("<img ") === -1, "title не должен попадать в разметку сырым тегом");
  // экранированные кавычки не могут разорвать атрибут title="..." — новых атрибутов не появляется
  assert.ok(html.indexOf('"alert(1)"') === -1, "кавычки в title должны быть экранированы");
  assert.ok(html.indexOf("&lt;script&gt;") !== -1);
  assert.ok(html.indexOf("&lt;img") !== -1);
  assert.ok(html.indexOf("&quot;alert(1)&quot;") !== -1);
});

// ------------------------------------------------------------------ sentryIssueItemHtml / sentryEventHtml

var sentryIssueItemHtml = SentryLogic.sentryIssueItemHtml;
var sentryEventHtml = SentryLogic.sentryEventHtml;

test("sentryIssueItemHtml: строка-переключатель с data-issue-id, ссылка в Sentry отдельной «↗», детали скрыты", function () {
  var html = sentryIssueItemHtml(baseIssue({ id: "16398" }));
  assert.ok(html.indexOf('data-issue-id="16398"') !== -1);
  assert.ok(html.indexOf('class="sentry-row sentry-row-toggle"') !== -1, "строка — переключатель, а не ссылка");
  assert.ok(html.indexOf('aria-expanded="false"') !== -1);
  assert.ok(html.indexOf('class="sentry-ext" href="https://sentry.example.ru/issues/1/"') !== -1);
  assert.ok(html.indexOf('class="sentry-details" hidden') !== -1);
});

test("sentryIssueItemHtml: без permalink нет «↗», withNewBadge даёт бейдж и is-new", function () {
  var html = sentryIssueItemHtml(baseIssue({ permalink: null, is_new: true }), { withNewBadge: true });
  assert.ok(html.indexOf("sentry-ext") === -1);
  assert.ok(html.indexOf("sentry-new-badge") !== -1);
  assert.ok(html.indexOf("is-new") !== -1);
});

function sampleEvent() {
  // по мотивам issue 16398 (k8s-vshgu-lms, 13.10.2026): message-событие крона + искусственное исключение
  return {
    date: "2026-10-13T12:28:04Z",
    message: "Не удалось отправить уведомление в канале: system",
    log_context: { code: 0, message: "Call to a member function notify() on null", notification_id: 175, user_id: 788 },
    exceptions: [{ type: "TypeError", value: "hasOneOfRoles(): Argument #1 ($user) must be of type User, null given",
      frames: [{ file: "app/Http/Controllers/Admin/UserCrudController.php", line: 252, function: "setupAssignRoleOperation", code: "$this->roles->hasOneOfRoles($user, [...]);" }] }],
    breadcrumbs: [{ ts: "12:28:04", category: "artisan.command", message: "Starting Artisan command: notification:send" }],
    tags: { environment: "development", server_name: "lms-cron-29864908-h486b", release: "48d05486d", url: "<b>x</b>" },
  };
}

test("sentryEventHtml: сообщение, log_context, исключение с кадром и кодом, крошки, теги", function () {
  var html = sentryEventHtml(sampleEvent());
  assert.ok(html.indexOf("Не удалось отправить уведомление в канале: system") !== -1);
  assert.ok(html.indexOf("<dt>notification_id</dt><dd>175</dd>") !== -1);
  assert.ok(html.indexOf("<b>TypeError</b>") !== -1);
  assert.ok(html.indexOf("UserCrudController.php:252</code>") !== -1);
  assert.ok(html.indexOf("hasOneOfRoles($user") !== -1, "строка кода кадра");
  assert.ok(html.indexOf("artisan.command") !== -1);
  assert.ok(html.indexOf("env: development") !== -1);
  assert.ok(html.indexOf("release 48d05486d") !== -1);
});

test("sentryEventHtml: значения экранируются (url с тегом не становится разметкой)", function () {
  var html = sentryEventHtml(sampleEvent());
  assert.ok(html.indexOf("<b>x</b>") === -1);
  assert.ok(html.indexOf("&lt;b&gt;x&lt;/b&gt;") !== -1);
});

test("sentryEventHtml: пустое событие и null не падают", function () {
  assert.ok(sentryEventHtml(null).indexOf("muted") !== -1);
  assert.ok(sentryEventHtml({}).indexOf("нет подробностей") !== -1);
});

var failed = 0;
tests.forEach(function (t) {
  try {
    t.fn();
    console.log("ok - " + t.name);
  } catch (err) {
    failed += 1;
    console.error("NOT OK - " + t.name);
    console.error(err && err.stack ? err.stack : err);
  }
});

console.log(tests.length - failed + "/" + tests.length + " passed");
process.exit(failed > 0 ? 1 : 0);
