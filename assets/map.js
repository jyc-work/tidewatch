/* tidewatch · 板块工作台联动 + 图谱工具栏（零依赖）
 * 数据来自内联 JSON（#sector-data），JS 只做：
 *   1. 工具栏筛选（类型 / 周期 / 模式）
 *   2. 选中态与右栏 Inspector 更新
 *   3. 重点板块标签
 * 不请求后端、不从表格文字反解析数据。
 */
(function () {
  "use strict";

  function init() {
    var el = document.getElementById("sector-data");
    var map = document.querySelector(".sector-map");
    if (!el || !map) return;

    var data = [];
    try { data = JSON.parse(el.textContent || "[]"); } catch (e) { data = []; }
    var byCode = {};
    data.forEach(function (d) { byCode[d.code] = d; });

    var svg = map.querySelector("svg.smap");
    var pts = Array.prototype.slice.call(map.querySelectorAll(".pt"));
    var listRows = document.querySelectorAll(".sl-row");
    var tableRows = document.querySelectorAll("table.grid-t tbody tr[data-code]");
    var state = { cat: "all", metric: "r1", mode: "scatter", q: "" };

    var labels = document.createElementNS("http://www.w3.org/2000/svg", "g");
    labels.setAttribute("class", "labels");
    if (svg) svg.appendChild(labels);

    function metricOf(p, k) {
      var v = p.getAttribute("data-" + k);
      return (v === "" || v === null) ? null : parseFloat(v);
    }

    function matchQ(code) {
      if (!state.q) return true;
      var d = byCode[code];
      var hay = ((d && d.name) || "") + " " + code;
      return hay.toLowerCase().indexOf(state.q) >= 0;
    }

    function apply() {
      pts.forEach(function (p) {
        var code = p.getAttribute("data-code");
        var show = (state.cat === "all" || p.getAttribute("data-cat") === state.cat)
                   && matchQ(code);
        p.style.display = show ? "" : "none";
        var v = metricOf(p, state.metric);
        if (v === null) { p.classList.remove("up", "down"); return; }
        p.classList.toggle("up", v >= 0);
        p.classList.toggle("down", v < 0);
        if (state.mode === "heat") {
          p.classList.add("heat");
          p.style.fillOpacity = Math.min(0.9, 0.2 + Math.abs(v) * 6).toFixed(2);
        } else {
          p.classList.remove("heat");
          p.style.fillOpacity = "";
        }
      });

      function filt(nodes) {
        var shown = 0, total = 0;
        Array.prototype.forEach.call(nodes, function (n) {
          var code = n.getAttribute("data-code");
          var d = byCode[code];
          var show = d && (state.cat === "all" || d.cat === state.cat) && matchQ(code);
          n.style.display = show ? "" : "none";
          total++;
          if (show) shown++;
        });
        return { shown: shown, total: total };
      }
      var r = filt(listRows);
      filt(tableRows);
      var count = document.querySelector(".filter-count");
      if (count) count.textContent = state.q ? r.shown + " / " + r.total : "";

      // 标签：当前可见中 |metric| 最大的 8 个
      while (labels.firstChild) labels.removeChild(labels.firstChild);
      var visible = pts.filter(function (p) { return p.style.display !== "none"; });
      visible.sort(function (a, b) {
        return Math.abs(metricOf(b, state.metric) || 0) -
               Math.abs(metricOf(a, state.metric) || 0);
      });
      visible.slice(0, 8).forEach(function (p) {
        var d = byCode[p.getAttribute("data-code")];
        if (!d) return;
        var t = document.createElementNS("http://www.w3.org/2000/svg", "text");
        t.setAttribute("class", "plabel");
        t.setAttribute("x", (parseFloat(p.getAttribute("cx")) + 6).toFixed(1));
        t.setAttribute("y", (parseFloat(p.getAttribute("cy")) - 4).toFixed(1));
        t.textContent = d.name;
        labels.appendChild(t);
      });
    }

    function setNum(id, v, cls) {
      var e = document.getElementById(id);
      if (e) { e.textContent = v; e.className = "num " + cls; }
    }
    function setText(id, v) {
      var e = document.getElementById(id);
      if (e) e.textContent = v;
    }

    function select(code) {
      [pts, listRows, tableRows].forEach(function (nodes) {
        Array.prototype.forEach.call(nodes, function (n) {
          n.classList.toggle("sel", n.getAttribute("data-code") === code);
        });
      });
      var d = byCode[code];
      if (!d) return;
      setText("ins-name", d.name);
      setText("ins-code", d.code);
      var st = document.getElementById("ins-stage");
      if (st) st.innerHTML = '<span class="badge ' + d.stage_cls + '">' + d.stage + "</span>";
      setNum("ins-r1", d.ret1, d.cls1);
      setNum("ins-r5", d.ret5, d.cls5);
      setNum("ins-r20", d.ret20, d.cls20);
      setText("ins-amt", d.amount);
      var sp = document.getElementById("ins-spark");
      if (sp) sp.innerHTML = d.spark || "";
      var lk = document.getElementById("ins-link");
      if (lk) lk.href = d.href;
      Array.prototype.forEach.call(tableRows, function (n) {
        if (n.getAttribute("data-code") === code && n.style.display !== "none") {
          n.scrollIntoView({ block: "center", behavior: "smooth" });
        }
      });
    }

    function bind(nodes) {
      Array.prototype.forEach.call(nodes, function (n) {
        n.addEventListener("click", function (e) {
          if (n.tagName === "A") e.preventDefault();   // 左栏是链接：拦截后只联动，不跳转
          select(n.getAttribute("data-code"));
        });
      });
    }
    bind(pts);
    bind(listRows);
    Array.prototype.forEach.call(tableRows, function (tr) {
      tr.addEventListener("click", function (e) {
        if (e.target.closest("a")) return;
        select(tr.getAttribute("data-code"));
      });
    });

    // 工具栏
    var tb = document.querySelector(".map-toolbar");
    if (tb) {
      tb.addEventListener("click", function (e) {
        var b = e.target.closest("button.tb");
        if (!b) return;
        var key = b.dataset.cat !== undefined ? "cat"
                : b.dataset.metric !== undefined ? "metric"
                : b.dataset.mode !== undefined ? "mode" : null;
        if (!key) return;
        state[key] = b.dataset[key];
        Array.prototype.forEach.call(tb.querySelectorAll("button.tb"), function (x) {
          if (x.dataset[key] !== undefined) x.classList.toggle("active", x === b);
        });
        apply();
      });
    }

    // 全屏放大
    var card = document.querySelector(".sector-map-card");
    var btn = document.querySelector(".map-expand");
    if (card && btn) {
      btn.addEventListener("click", function () {
        card.classList.toggle("expanded");
        btn.textContent = card.classList.contains("expanded") ? "✕" : "⤢";
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") {
          card.classList.remove("expanded");
          btn.textContent = "⤢";
        }
      });
    }

    // 左栏排序（点列头）
    var head = document.querySelector(".sl-head");
    var listBox = document.querySelector(".sector-list");
    if (head && listBox) {
      var sortState = { key: null, asc: true };
      head.addEventListener("click", function (e) {
        var b = e.target.closest(".sl-sort");
        if (!b) return;
        var key = b.getAttribute("data-sort");
        sortState.asc = sortState.key === key ? !sortState.asc : true;
        sortState.key = key;
        Array.prototype.forEach.call(head.querySelectorAll(".sl-sort"), function (x) {
          var on = x === b;
          x.classList.toggle("active", on);
          var sm = x.querySelector(".sm");
          if (sm) sm.textContent = on ? (sortState.asc ? " ▲" : " ▼") : "";
        });
        var items = Array.prototype.slice.call(listBox.querySelectorAll(".sl-row"));
        items.sort(function (a, b2) {
          var da = byCode[a.getAttribute("data-code")] || {};
          var db = byCode[b2.getAttribute("data-code")] || {};
          if (key === "name") {
            var va = da.name || "", vb = db.name || "";
            return sortState.asc ? va.localeCompare(vb, "zh-Hans-CN")
                                 : vb.localeCompare(va, "zh-Hans-CN");
          }
          if (key === "stage") {
            var sa = da.stage || "", sb = db.stage || "";
            return sortState.asc ? sa.localeCompare(sb, "zh-Hans-CN")
                                 : sb.localeCompare(sa, "zh-Hans-CN");
          }
          var na = (da[key] === null || da[key] === undefined) ? -Infinity : da[key];
          var nb = (db[key] === null || db[key] === undefined) ? -Infinity : db[key];
          return sortState.asc ? na - nb : nb - na;
        });
        items.forEach(function (r) { listBox.appendChild(r); });
      });
    }

    // 搜索框：同时过滤左栏与图谱圆点
    var searchInput = document.querySelector(".list-filter");
    if (searchInput) {
      searchInput.addEventListener("input", function () {
        state.q = searchInput.value.trim().toLowerCase();
        apply();
      });
    }

    apply();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
