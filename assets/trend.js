/* tidewatch · 个股走势周期切换（零依赖）
 * 页面：stock.html（#trend-img 带 data-market / data-code）
 * 数据源：新浪财经静态图（分时/日K/周K/月K），无跨域、无需接口。
 */
(function () {
  "use strict";

  function init() {
    var img = document.getElementById("trend-img");
    if (!img) return;
    var market = img.getAttribute("data-market") || "";
    var code = img.getAttribute("data-code") || "";
    var tabs = Array.prototype.slice.call(document.querySelectorAll(".trend-tab"));

    tabs.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var period = btn.getAttribute("data-period") || "daily";
        img.src = "https://image.sinajs.cn/newchart/" + period +
                  "/n/" + market + code + ".gif";
        tabs.forEach(function (o) { o.classList.remove("active"); });
        btn.classList.add("active");
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
