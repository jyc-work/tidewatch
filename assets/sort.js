/* tidewatch · 表格排序（无依赖，本地加载）
 *
 * 给所有 table.data 的表头加点击排序。
 * 解析规则：
 *   "-" / ""        -> 视为 -Infinity（始终排最后）
 *   "+1.23%" "1.2%" -> 数值
 *   "1,234.5"       -> 去掉千分位
 *   其他            -> 按文本比较（中文用 localeCompare）
 *
 * 表头带 data-nosort 的列不参与排序。
 */
(function () {
  "use strict";

  function parseCell(text) {
    var s = (text || "").trim();
    if (s === "" || s === "-" || s === "—") return { num: null, text: "" };
    var cleaned = s.replace(/,/g, "").replace(/%$/, "").replace(/^\+/, "");
    var n = parseFloat(cleaned);
    if (!isNaN(n) && /^[+\-]?[\d,]+(\.\d+)?%?$/.test(s)) {
      return { num: n, text: s };
    }
    return { num: null, text: s };
  }

  function sortTable(table, colIndex, asc) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.prototype.slice.call(tbody.rows);
    rows.sort(function (a, b) {
      var ca = a.cells[colIndex], cb = b.cells[colIndex];
      if (!ca || !cb) return 0;
      var pa = parseCell(ca.textContent), pb = parseCell(cb.textContent);
      // 数值列：数字优先；null 一律排最后
      if (pa.num !== null || pb.num !== null) {
        if (pa.num === null) return 1;
        if (pb.num === null) return -1;
        return asc ? pa.num - pb.num : pb.num - pa.num;
      }
      var r = pa.text.localeCompare(pb.text, "zh-Hans-CN");
      return asc ? r : -r;
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
  }

  function initRowLinks() {
    // 整行可点击（one delegated listener per table，比每格一个 <a> 省 DOM）
    document.querySelectorAll("table.rowlink").forEach(function (table) {
      table.addEventListener("click", function (e) {
        if (e.target.closest("a")) return;            // 单元格内链接优先
        var tr = e.target.closest("tbody tr[data-href]");
        if (tr) window.location.href = tr.getAttribute("data-href");
      });
    });
  }

  function init() {
    initRowLinks();
    var tables = document.querySelectorAll("table.data");
    tables.forEach(function (table) {
      var headRow = table.tHead && table.tHead.rows[0];
      if (!headRow) return;
      Array.prototype.forEach.call(headRow.cells, function (th, i) {
        if (th.hasAttribute("data-nosort")) return;
        th.style.cursor = "pointer";
        th.title = "点击排序";
        var state = 0; // 0=未排, 1=升序, 2=降序
        var mark = document.createElement("span");
        mark.className = "sort-mark";
        mark.textContent = "";
        th.appendChild(mark);
        th.addEventListener("click", function () {
          // 同一表内其它列清除标记
          Array.prototype.forEach.call(headRow.cells, function (o) {
            if (o !== th) {
              var m = o.querySelector(".sort-mark");
              if (m) m.textContent = "";
              o.removeAttribute("data-dir");
            }
          });
          state = state === 1 ? 2 : 1;
          th.setAttribute("data-dir", state === 1 ? "asc" : "desc");
          mark.textContent = state === 1 ? " ▲" : " ▼";
          sortTable(table, i, state === 1);
        });
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
