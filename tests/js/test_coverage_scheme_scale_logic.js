/*
 * Юнит-тест чистой JS-логики масштабирования схемы продукта на странице покрытия
 * (ui/coverage-scheme-logic.js: pmCanvasSvgAttrs — атрибуты обёртки
 * <svg class="pm-canvas-svg"> вокруг схемы, само масштабирование под ширину
 * карточки/скролл на узких экранах — в CSS, см. ui/style.css) — без DOM,
 * запускается напрямую через node (см. tests/test_coverage_scheme_scale_logic_js.py,
 * который дёргает этот файл через subprocess). coverage.js подключает
 * ui/coverage-scheme-logic.js и использует window.CoverageSchemeLogic.
 */
"use strict";

var assert = require("assert");
var path = require("path");

var CoverageSchemeLogic = require(path.join(__dirname, "..", "..", "ui", "coverage-scheme-logic.js"));
var pmCanvasSvgAttrs = CoverageSchemeLogic.pmCanvasSvgAttrs;

var tests = [];
function test(name, fn) {
  tests.push({ name: name, fn: fn });
}

test("pmCanvasSvgAttrs: viewBox от 0,0 до canvas.width/height", function () {
  var attrs = pmCanvasSvgAttrs({ width: 1440, height: 900 });
  assert.strictEqual(attrs.viewBox, "0 0 1440 900");
});

test("pmCanvasSvgAttrs: width/height — натуральный размер холста (для аспекта в CSS)", function () {
  var attrs = pmCanvasSvgAttrs({ width: 1440, height: 900 });
  assert.strictEqual(attrs.width, "1440");
  assert.strictEqual(attrs.height, "900");
});

test("pmCanvasSvgAttrs: работает на произвольном (в т.ч. небольшом) холсте — demo/fallback-раскладка", function () {
  var attrs = pmCanvasSvgAttrs({ width: 620, height: 380 });
  assert.strictEqual(attrs.viewBox, "0 0 620 380");
  assert.strictEqual(attrs.width, "620");
  assert.strictEqual(attrs.height, "380");
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
