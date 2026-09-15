(function (w) {
  var KEY = "mopswork_dismissed_jobs";

  function empty() {
    return { ids: [], fps: [], urls: [], titles: [], recs: [] };
  }

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      if (!raw) return empty();
      var d = JSON.parse(raw);
      return {
        ids: d.ids || [],
        fps: d.fps || [],
        urls: d.urls || [],
        titles: d.titles || [],
        recs: d.recs || [],
      };
    } catch (e) {
      return empty();
    }
  }

  function save(d) {
    try { localStorage.setItem(KEY, JSON.stringify(d)); } catch (e) {}
  }

  function norm(s) {
    return String(s || "").trim().toLowerCase().replace(/\s+/g, " ");
  }

  function jobFp(job) {
    if (!job) return "";
    return norm(job.title) + "|" + norm(job.company);
  }

  function jobUrlKey(job) {
    if (!job || !job.url) return "";
    return String(job.url).split("?")[0].trim().toLowerCase();
  }

  function titleKey(job) {
    return job ? norm(job.title) : "";
  }

  function remember(job, jobId, status) {
    var d = load();
    if (jobId && d.ids.indexOf(jobId) === -1) d.ids.push(jobId);
    var fp = jobFp(job);
    if (fp && fp !== "|" && d.fps.indexOf(fp) === -1) d.fps.push(fp);
    var u = jobUrlKey(job);
    if (u && d.urls.indexOf(u) === -1) d.urls.push(u);
    var t = titleKey(job);
    if (t && d.titles.indexOf(t) === -1) d.titles.push(t);
    var rec = {
      id: jobId || "",
      status: status || "not_applicable",
      title: job ? (job.title || "") : "",
      company: job ? (job.company || "") : "",
      url: job ? (job.url || "") : "",
      location: job ? (job.location || "") : "",
      match_score: job ? (job.match_score || 0) : 0,
    };
    var found = false;
    for (var i = 0; i < d.recs.length; i++) {
      var sameId = rec.id && d.recs[i].id === rec.id;
      var sameFp = rec.title && norm(d.recs[i].title) === norm(rec.title) && norm(d.recs[i].company) === norm(rec.company);
      var sameTitle = rec.title && !rec.company && norm(d.recs[i].title) === norm(rec.title);
      if (sameId || sameFp || sameTitle) {
        d.recs[i] = rec;
        found = true;
        break;
      }
    }
    if (!found && (rec.id || rec.title)) d.recs.push(rec);
    save(d);
  }

  function forget(job, jobId) {
    var d = load();
    d.ids = d.ids.filter(function (id) { return id !== jobId; });
    var fp = jobFp(job);
    if (fp) d.fps = d.fps.filter(function (x) { return x !== fp; });
    var u = jobUrlKey(job);
    if (u) d.urls = d.urls.filter(function (x) { return x !== u; });
    var t = titleKey(job);
    if (t) d.titles = d.titles.filter(function (x) { return x !== t; });
    d.recs = d.recs.filter(function (rec) {
      if (rec.id && rec.id === jobId) return false;
      if (job && norm(rec.title) === titleKey(job) && (!job.company || norm(rec.company) === norm(job.company))) return false;
      return true;
    });
    save(d);
  }

  function recFor(job) {
    if (!job) return null;
    var d = load();
    var fp = jobFp(job);
    var u = jobUrlKey(job);
    var t = titleKey(job);
    for (var i = 0; i < d.recs.length; i++) {
      var rec = d.recs[i];
      if (job.job_id && rec.id === job.job_id) return rec;
      if (fp && fp !== "|" && jobFp(rec) === fp) return rec;
      if (u && jobUrlKey(rec) === u) return rec;
      if (t && norm(rec.title) === t) return rec;
    }
    return null;
  }

  function isDismissed(job) {
    if (!job) return false;
    if (job.status) return true;
    var rec = recFor(job);
    if (rec && rec.status) return true;
    var d = load();
    if (job.job_id && d.ids.indexOf(job.job_id) !== -1) return true;
    if (d.fps.indexOf(jobFp(job)) !== -1) return true;
    var u = jobUrlKey(job);
    if (u && d.urls.indexOf(u) !== -1) return true;
    var t = titleKey(job);
    if (t && d.titles.indexOf(t) !== -1) return true;
    return false;
  }

  function applyStatus(job) {
    var rec = recFor(job);
    if (rec && rec.status && !job.status) job.status = rec.status;
    return job;
  }

  function allRecs() {
    return load().recs || [];
  }

  w.MopsTracker = {
    load: load,
    remember: remember,
    forget: forget,
    isDismissed: isDismissed,
    applyStatus: applyStatus,
    recFor: recFor,
    allRecs: allRecs,
    jobFp: jobFp,
    jobUrlKey: jobUrlKey,
  };
})(window);
