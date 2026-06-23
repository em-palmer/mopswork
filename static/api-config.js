// Auto-detect API backend URL — local dev vs live site
(function () {
  var host = window.location.hostname;
  if (host === "localhost" || host === "127.0.0.1") {
    window.API_BASE = "http://localhost:8003";
  } else {
    window.API_BASE = "https://mopswork.onrender.com";
  }
})();