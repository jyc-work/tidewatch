/* tidewatch · 列表页搜索（零依赖）
 * 过滤页内 table.grid-t 的行（席位 / 个股 / 雷达页）。
 * 板块工作台的搜索由 map.js 处理（同时过滤左栏与图谱圆点）。
 * 快捷键 "/" 聚焦。
 */
(function () {
  "use strict";

  function init() {
    var input = document.querySelector(".list-filter");
    if (!input) return;
    var count = document.querySelector(".filter-count");
    var tables = Array.prototype.slice.call(document.querySelectorAll("table.grid-t"));

    function apply() {
      var q = input.value.trim().toLowerCase();
      var shown = 0, total = 0;
      tables.forEach(function (t) {
        var tb = t.tBodies[0];
        if (!tb) return;
        Array.prototype.forEach.call(tb.rows, function (tr) {
          total++;
          var hit = !q || tr.textContent.toLowerCase().indexOf(q) >= 0;
          tr.style.display = hit ? "" : "none";
          if (hit) shown++;
        });
      });
      if (count) count.textContent = q ? shown + " / " + total : "";
    }

    input.addEventListener("input", apply);

    document.addEventListener("keydown", function (e) {
      if (e.key === "/" && document.activeElement !== input) {
        e.preventDefault();
        input.focus();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
