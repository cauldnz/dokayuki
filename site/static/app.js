/* Mode (Normie/Nerd), theme and Japanese toggles. Preferences in localStorage only; no cookies, no tracking. */
(function () {
  var root = document.documentElement;
  var KEY = root.getAttribute("data-mode-key") || "hpo-mode";
  function setMode(m, persist) {
    root.setAttribute("data-mode", m);
    document.querySelectorAll(".mode-btn").forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-set-mode") === m)); });
    if (persist) { try { localStorage.setItem(KEY, m); } catch (e) {} }
  }
  var q = new URLSearchParams(location.search).get("mode");
  setMode(q === "nerd" || q === "normie" ? q : root.getAttribute("data-mode") || "normie", false);
  document.querySelectorAll(".mode-btn").forEach(function (b) { b.addEventListener("click", function () { setMode(b.getAttribute("data-set-mode"), true); }); });
  var tb = document.getElementById("theme-btn");
  if (tb) tb.addEventListener("click", function () {
    var dark = root.getAttribute("data-theme") === "dark" || (!root.getAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
    var t = dark ? "light" : "dark"; root.setAttribute("data-theme", t); try { localStorage.setItem("hpo-theme", t); } catch (e) {}
  });
  var jb = document.getElementById("ja-btn");
  if (jb) {
    try { if (localStorage.getItem("hpo-ja") === "1") { root.setAttribute("data-ja", "1"); jb.setAttribute("aria-pressed", "true"); } } catch (e) {}
    jb.addEventListener("click", function () {
      var on = root.getAttribute("data-ja") !== "1"; root.setAttribute("data-ja", on ? "1" : "0"); jb.setAttribute("aria-pressed", String(on));
      try { localStorage.setItem("hpo-ja", on ? "1" : "0"); } catch (e) {}
    });
  }
})();
