/**
 * MOpsWork — Job Scanner Widget
 * Fetches live job listings with Status column (4th), compact layout.
 */

(function () {
  "use strict";

  var API_BASE = window.API_BASE || "http://localhost:8003";
  const STATUSES = ["", "applied", "interviewing", "offer", "withdrawn", "rejected", "not_applicable"];

  let allJobs = [];
  let stats = null;
  let profile = null;
  const filters = {
    min_score: 0, max_score: 100, source: "all",
    city: "", work_type: "", seniority: "", keyword: "",
    country: "", salary_min: "", salary_max: "",
    posted_since: "1w",
  };

  let tbodyEl, countEl, avgEl, loadingEl, sourceSelect, profileStatusEl, cvCompareToggle;

  function scoreClass(s) {
    if (s >= 70) return "score-high";
    if (s >= 40) return "score-mid";
    return "score-low";
  }
  function scoreLabel(s) {
    if (s >= 70) return "Strong Match";
    if (s >= 40) return "Good Match";
    return "Possible Match";
  }

  function saveFilters() {
    try {
      var copy = {};
      Object.keys(filters).forEach(function(k) { copy[k] = filters[k]; });
      var c = document.getElementById("cvCompareToggle");
      copy.cv_compare = c ? c.checked : false;
      sessionStorage.setItem("mopswork_filters", JSON.stringify(copy));
    } catch (e) {}
  }

  function loadFilters() {
    try {
      var raw = sessionStorage.getItem("mopswork_filters");
      if (raw) {
        var saved = JSON.parse(raw);
        Object.assign(filters, saved);
      }
    } catch (e) {}
    if (!filters.posted_since) filters.posted_since = "1w";
  }

  function restoreFormFromFilters() {
    var m = {city:"filterCity",work_type:"filterWorkType",seniority:"filterSeniority",keyword:"filterKeyword",country:"filterCountry","posted_since":"filterPostedSince",source:"filterSource"};
    Object.keys(m).forEach(function(k) {
      var el = document.getElementById(m[k]);
      if (el && filters[k]) el.value = filters[k];
    });
    if (filters.salary_min || filters.salary_max) {
      var salaryEl = document.getElementById("filterSalary");
      if (salaryEl) {
        var v = filters.salary_min + "-" + filters.salary_max;
        var opt = salaryEl.querySelector('option[value="' + v + '"]');
        if (opt) salaryEl.value = v;
      }
    }
    var minSc = filters.min_score || 0;
    var maxSc = filters.max_score || 100;
    if (minSc > 0 || maxSc < 100) {
      var matchEl = document.getElementById("filterMatch");
      if (matchEl) {
        var mv = minSc + "-" + maxSc;
        var mopt = matchEl.querySelector('option[value="' + mv + '"]');
        if (mopt) matchEl.value = mv;
      }
    }
  }
  function parsePostedDate(value) {
    if (value == null) return null;
    var s = String(value).trim();
    if (!s) return null;
    var sl = s.toLowerCase();
    var now = Date.now();
    if (sl === "today" || sl === "just now" || sl === "just posted") return new Date(now);
    if (sl === "yesterday") return new Date(now - 86400000);
    var m = sl.match(/^(\d+)\s*(minutes?|mins?)\s+ago$/);
    if (m) return new Date(now - parseInt(m[1], 10) * 60000);
    m = sl.match(/^(\d+)\s*(hours?|hrs?)\s+ago$/);
    if (m) return new Date(now - parseInt(m[1], 10) * 3600000);
    m = sl.match(/^(\d+)\s+days?\s+ago$/);
    if (m) return new Date(now - parseInt(m[1], 10) * 86400000);
    m = sl.match(/^(\d+)\s+weeks?\s+ago$/);
    if (m) return new Date(now - parseInt(m[1], 10) * 7 * 86400000);
    if (/^\d{10,13}$/.test(s)) {
      var ts = parseInt(s, 10);
      if (ts > 10000000000) ts = ts / 1000;
      return new Date(ts * 1000);
    }
    var iso = Date.parse(s);
    if (!isNaN(iso)) return new Date(iso);
    var months = {jan:0,january:0,feb:1,february:1,mar:2,march:2,apr:3,april:3,may:4,jun:5,june:5,jul:6,july:6,aug:7,august:7,sep:8,sept:8,september:8,oct:9,october:9,nov:10,november:10,dec:11,december:11};
    m = s.match(/^(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?$/);
    var day, monthName, year;
    if (m) {
      day = parseInt(m[1], 10); monthName = m[2]; year = m[3];
    } else {
      m = s.match(/^([A-Za-z]+)\s+(\d{1,2})(?:,?\s+(\d{4}))?$/);
      if (!m) return null;
      monthName = m[1]; day = parseInt(m[2], 10); year = m[3];
    }
    var month = months[monthName.toLowerCase()];
    if (month == null) return null;
    var y = year ? parseInt(year, 10) : new Date().getFullYear();
    var d = new Date(Date.UTC(y, month, day));
    if (isNaN(d.getTime())) return null;
    if (d.getTime() > now + 86400000) d = new Date(Date.UTC(y - 1, month, day));
    return d;
  }

  function jobMatchesPostedSince(job, since) {
    if (!since || since === "all") return true;
    var posted = parsePostedDate(job.posted_date);
    if (!posted) return false;
    var sec = (Date.now() - posted.getTime()) / 1000;
    if (since === "24h") return sec <= 86400;
    if (since === "3d") return sec <= 259200;
    if (since === "1w") return sec <= 604800;
    if (since === "older") return sec > 604800;
    return true;
  }

  function timeAgo(ds) {
    if (!ds) return "";
    var d = parsePostedDate(ds) || new Date(ds);
    if (isNaN(d.getTime())) return String(ds);
    var dy = Math.floor((Date.now() - d.getTime()) / 86400000);
    if (dy <= 0) return "Today";
    if (dy === 1) return "Yesterday";
    if (dy < 7) return dy + "d ago";
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  }
  function esc(s) {
    if (!s) return "";
    const d = document.createElement("div"); d.textContent = s; return d.innerHTML;
  }

  async function updateStatus(jobId, newStatus) {
    var job = null;
    for (var i = 0; i < allJobs.length; i++) {
      if (allJobs[i].job_id === jobId) { job = allJobs[i]; break; }
    }
    const fd = new URLSearchParams();
    fd.set("status", newStatus);
    if (job) {
      fd.set("title", job.title || "");
      fd.set("company", job.company || "");
      fd.set("url", job.url || "");
    }
    if (newStatus) {
      if (window.MopsTracker) window.MopsTracker.remember(job, jobId, newStatus);
      else rememberDismissed(job, jobId, newStatus);
    } else {
      if (window.MopsTracker) window.MopsTracker.forget(job, jobId);
      else forgetDismissed(job, jobId);
    }
    if (newStatus) {
      allJobs = allJobs.filter(function(j) { return j.job_id !== jobId; });
      renderTable();
    }
    try {
      await fetch(API_BASE + "/api/applications/" + encodeURIComponent(jobId), {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: fd.toString(),
      });
    } catch (err) { console.error("Status update failed:", err); }
    fetchJobs();
  }

  var DISMISSED_KEY = "mopswork_dismissed_jobs";

  function loadDismissed() {
    try {
      var raw = localStorage.getItem(DISMISSED_KEY);
      if (!raw) return { ids: [], fps: [], urls: [], recs: [] };
      var d = JSON.parse(raw);
      return {
        ids: d.ids || [],
        fps: d.fps || [],
        urls: d.urls || [],
        recs: d.recs || [],
      };
    } catch (e) {
      return { ids: [], fps: [], urls: [], recs: [] };
    }
  }

  function saveDismissed(d) {
    try { localStorage.setItem(DISMISSED_KEY, JSON.stringify(d)); } catch (e) {}
  }

  function jobFp(job) {
    if (!job) return "";
    return String(job.title || "").trim().toLowerCase() + "|" + String(job.company || "").trim().toLowerCase();
  }

  function jobUrlKey(job) {
    if (!job || !job.url) return "";
    return String(job.url).split("?")[0].trim().toLowerCase();
  }

  function rememberDismissed(job, jobId, status) {
    var d = loadDismissed();
    if (jobId && d.ids.indexOf(jobId) === -1) d.ids.push(jobId);
    var fp = jobFp(job);
    if (fp && fp !== "|" && d.fps.indexOf(fp) === -1) d.fps.push(fp);
    var u = jobUrlKey(job);
    if (u && d.urls.indexOf(u) === -1) d.urls.push(u);
    var rec = {
      id: jobId || "",
      status: status || "not_applicable",
      title: job ? (job.title || "") : "",
      company: job ? (job.company || "") : "",
      url: job ? (job.url || "") : "",
    };
    var found = false;
    for (var i = 0; i < d.recs.length; i++) {
      if (d.recs[i].id === rec.id || (rec.title && d.recs[i].title === rec.title && d.recs[i].company === rec.company)) {
        d.recs[i] = rec;
        found = true;
        break;
      }
    }
    if (!found && rec.id) d.recs.push(rec);
    saveDismissed(d);
  }

  function forgetDismissed(job, jobId) {
    var d = loadDismissed();
    d.ids = d.ids.filter(function(id) { return id !== jobId; });
    var fp = jobFp(job);
    if (fp) d.fps = d.fps.filter(function(x) { return x !== fp; });
    var u = jobUrlKey(job);
    if (u) d.urls = d.urls.filter(function(x) { return x !== u; });
    d.recs = d.recs.filter(function(rec) {
      if (rec.id && rec.id === jobId) return false;
      if (job && rec.title === (job.title || "") && rec.company === (job.company || "")) return false;
      return true;
    });
    saveDismissed(d);
  }

  async function replayDismissedToServer() {
    var jobs = [];
    try {
      var params = new URLSearchParams({ limit: "200", exclude_na: "false", posted_since: "1w" });
      var r = await fetch(API_BASE + "/api/jobs?" + params);
      if (r.ok) jobs = await r.json();
    } catch (e) {}
    var recs = window.MopsTracker ? window.MopsTracker.allRecs() : ((loadDismissed().recs) || []);
    var recById = {};
    recs.forEach(function(rec) { if (rec && rec.id) recById[rec.id] = rec; });
    var posted = {};
    for (var i = 0; i < jobs.length; i++) {
      var job = jobs[i];
      if (!job || !job.job_id) continue;
      if (window.MopsTracker) window.MopsTracker.applyStatus(job);
      if (!isDismissed(job) && !job.status) continue;
      var rec = recById[job.job_id] || (window.MopsTracker && window.MopsTracker.recFor(job)) || {};
      var fd = new URLSearchParams();
      fd.set("status", rec.status || job.status || "not_applicable");
      fd.set("title", job.title || rec.title || "");
      fd.set("company", job.company || rec.company || "");
      fd.set("url", job.url || rec.url || "");
      posted[job.job_id] = true;
      try {
        await fetch(API_BASE + "/api/applications/" + encodeURIComponent(job.job_id), {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: fd.toString(),
        });
      } catch (e) {}
    }
    for (var j = 0; j < recs.length; j++) {
      var rec2 = recs[j];
      if (!rec2 || !rec2.id || !rec2.status || !rec2.title || posted[rec2.id]) continue;
      var fd2 = new URLSearchParams();
      fd2.set("status", rec2.status);
      fd2.set("title", rec2.title);
      if (rec2.company) fd2.set("company", rec2.company);
      if (rec2.url) fd2.set("url", rec2.url);
      try {
        await fetch(API_BASE + "/api/applications/" + encodeURIComponent(rec2.id), {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: fd2.toString(),
        });
      } catch (e) {}
    }
  }

  function isDismissed(job) {
    if (window.MopsTracker) return window.MopsTracker.isDismissed(job);
    if (!job) return false;
    if (job.status) return true;
    var d = loadDismissed();
    if (job.job_id && d.ids.indexOf(job.job_id) !== -1) return true;
    if (d.fps.indexOf(jobFp(job)) !== -1) return true;
    var u = jobUrlKey(job);
    if (u && d.urls.indexOf(u) !== -1) return true;
    return false;
  }

  async function fetchJobs() {
    loadingEl?.classList.remove("hidden");
    try {
      const p = new URLSearchParams({ limit: 200 });
      if (filters.min_score > 0) p.set("min_score", filters.min_score);
      if (filters.max_score < 100) p.set("max_score", filters.max_score);
      if (filters.source !== "all") p.set("source", filters.source);
      if (filters.city) p.set("city", filters.city);
      if (filters.work_type) p.set("work_type", filters.work_type);
      if (filters.seniority) p.set("seniority", filters.seniority);
      if (filters.keyword) p.set("keyword", filters.keyword);
      if (filters.country) p.set("country", filters.country);
      if (filters.salary_min) p.set("salary_min", filters.salary_min);
      if (filters.salary_max) p.set("salary_max", filters.salary_max);
      if (filters.posted_since) p.set("posted_since", filters.posted_since);
      if (cvCompareToggle?.checked) p.set("cv_compare", "true");
      p.set("exclude_na", "true");

      const r = await fetch(API_BASE + "/api/jobs?" + p);
      if (!r.ok) throw new Error("HTTP " + r.status);
      const rows = await r.json();
      allJobs = rows.map(function(job) {
        if (window.MopsTracker) window.MopsTracker.applyStatus(job);
        return job;
      }).filter(function(job) { return !isDismissed(job); });
      renderTable();
    } catch (err) {
      console.error("Fetch failed:", err);
      if (tbodyEl) tbodyEl.innerHTML = '<tr class="jobs-error"><td colspan="13">Backend not running on port 8003.</td></tr>';
    } finally { loadingEl?.classList.add("hidden"); }
  }

  async function fetchStats() {
    try {
      const r = await fetch(API_BASE + "/api/stats");
      if (!r.ok) return;
      stats = await r.json();
      if (countEl) countEl.textContent = (stats.total_jobs || 0).toLocaleString();
      if (avgEl) avgEl.textContent = stats.avg_match ? stats.avg_match + "%" : "0%";
    } catch {}
  }

  async function fetchSources() {
    try {
      const r = await fetch(API_BASE + "/api/jobs/sources");
      if (!r.ok) return;
      const d = await r.json();
      if (sourceSelect && d.sources) {
        d.sources.forEach(function(s) {
          var o = document.createElement("option");
          o.value = s.toLowerCase();
          o.textContent = s;
          sourceSelect.appendChild(o);
        });
      }
    } catch {}
  }

  var CV_DB = "mopswork_cv";
  var CV_META_KEY = "mopswork_cv_name";

  function openCvDb() {
    return new Promise(function(resolve, reject) {
      var req = indexedDB.open(CV_DB, 1);
      req.onupgradeneeded = function() {
        if (!req.result.objectStoreNames.contains("files")) req.result.createObjectStore("files");
      };
      req.onsuccess = function() { resolve(req.result); };
      req.onerror = function() { reject(req.error); };
    });
  }

  async function saveCvLocal(file, name) {
    try { localStorage.setItem(CV_META_KEY, name || file.name); } catch (e) {}
    try {
      var db = await openCvDb();
      await new Promise(function(resolve, reject) {
        var tx = db.transaction("files", "readwrite");
        tx.objectStore("files").put({ file: file, name: name || file.name }, "latest");
        tx.oncomplete = resolve;
        tx.onerror = function() { reject(tx.error); };
      });
    } catch (e) {}
  }

  async function loadCvLocal() {
    try {
      var db = await openCvDb();
      return await new Promise(function(resolve, reject) {
        var tx = db.transaction("files", "readonly");
        var q = tx.objectStore("files").get("latest");
        q.onsuccess = function() { resolve(q.result || null); };
        q.onerror = function() { reject(q.error); };
      });
    } catch (e) {
      return null;
    }
  }

  async function clearCvLocal() {
    try { localStorage.removeItem(CV_META_KEY); } catch (e) {}
    try {
      var db = await openCvDb();
      await new Promise(function(resolve, reject) {
        var tx = db.transaction("files", "readwrite");
        tx.objectStore("files").delete("latest");
        tx.oncomplete = resolve;
        tx.onerror = function() { reject(tx.error); };
      });
    } catch (e) {}
  }

  async function postCv(file, name) {
    var lastErr = null;
    for (var attempt = 1; attempt <= 6; attempt++) {
      try {
        var fd = new FormData();
        fd.append("file", file);
        fd.append("name", name || file.name);
        var r = await fetch(API_BASE + "/api/profile/upload", { method: "POST", body: fd });
        if (r.ok) return await r.json();
        lastErr = new Error("Upload failed: " + r.status);
      } catch (e) {
        lastErr = e;
      }
      await new Promise(function(res) { setTimeout(res, 4000 * attempt); });
    }
    throw lastErr || new Error("Upload failed");
  }

  async function fetchProfile() {
    try {
      const r = await fetch(API_BASE + "/api/profile");
      if (!r.ok) return;
      profile = await r.json();
      var wanted = "";
      try { wanted = localStorage.getItem(CV_META_KEY) || ""; } catch (e) {}
      if (wanted && profile && profile.name && profile.name !== wanted) {
        var local = await loadCvLocal();
        if (local && local.file) {
          profile = await postCv(local.file, local.name || wanted);
        }
      } else if (wanted && (!profile || !profile.has_cv)) {
        var local2 = await loadCvLocal();
        if (local2 && local2.file) {
          profile = await postCv(local2.file, local2.name || wanted);
        }
      }
      updateProfileUI();
    } catch {}
  }

  async function uploadCV(file, name) {
    var label = name || file.name;
    await saveCvLocal(file, label);
    try {
      profile = await postCv(file, label);
      updateProfileUI();
      if (cvCompareToggle) cvCompareToggle.checked = true;
      fetchJobs();
    } catch (e) { console.error(e); alert("CV upload failed. The September file is saved in this browser and will retry when the API is awake."); }
  }

  async function deleteProfile() {
    await clearCvLocal();
    try { await fetch(API_BASE + "/api/profile", { method: "DELETE" }); profile = null; updateProfileUI(); fetchJobs(); } catch {}
  }

  async function triggerScrape() {
    var btn = document.querySelector(".jobs-refresh");
    if (btn) { btn.disabled = true; btn.textContent = "Scanning..."; }
    try { await fetch(API_BASE + "/api/scrape", { method: "POST" }); await Promise.all([fetchJobs(), fetchStats()]); }
    catch (e) { console.error(e); }
    finally { if (btn) { btn.disabled = false; btn.textContent = "Refresh Jobs"; } }
  }

  function updateProfileUI() {
    if (!profileStatusEl) return;
    if (profile && profile.has_cv) {
      profileStatusEl.innerHTML =
        '<span class="profile-badge profile-active"><span class="profile-dot"></span>CV: ' + esc(profile.name || "Uploaded") + ' (' + profile.skill_count + ' skills)</span>' +
        '<button class="profile-remove-btn" title="Remove CV">&times;</button>';
      var b = profileStatusEl.querySelector(".profile-remove-btn");
      if (b) b.addEventListener("click", deleteProfile);
    } else {
      profileStatusEl.innerHTML = '<span class="profile-badge profile-inactive">No CV uploaded</span>';
    }
  }

  function statusLabel(s) { if (s === "not_applicable") return "N/A"; return s ? s.charAt(0).toUpperCase() + s.slice(1) : "None"; }
  function statusClass(s) { return s ? "status-" + s : ""; }

  function renderTable() {
    if (!tbodyEl) return;
    // Update the match counter from the current filtered results
    var jobs = allJobs.filter(function(job) {
      if (isDismissed(job)) return false;
      return jobMatchesPostedSince(job, filters.posted_since);
    });
    if (countEl) countEl.textContent = jobs.length.toLocaleString();
    if (avgEl && jobs.length > 0) {
      var sum = 0;
      for (var i = 0; i < jobs.length; i++) sum += jobs[i].match_score || 0;
      avgEl.textContent = Math.round(sum / jobs.length) + "%";
    } else if (avgEl) {
      avgEl.textContent = "0%";
    }
    if (jobs.length === 0) {
      tbodyEl.innerHTML = '<tr class="jobs-empty"><td colspan="13">No matching jobs found.</td></tr>';
      return;
    }

    tbodyEl.innerHTML = jobs.map(function(job) {
      var skills = job.matched_skills || [];
      var gap = (job.skills_gap || []).slice(0, 6);
      var keySkills = job.key_skills || [];
      var sd = job.score_detail || {};
      var detailHtml = Object.entries(sd).filter(function(e){return e[1] > 0;}).map(function(e){return '<span class="jobs-score-detail-tag">' + e[0] + ':' + e[1] + '</span>';}).join("");
      var curStatus = job.status || "";

      return '<tr class="jobs-row">\
        <td class="jobs-title-cell">\
          <a href="' + esc(job.url) + '" target="_blank" rel="noopener" class="jobs-title">' + esc(job.title) + '</a>\
          <span class="jobs-company">' + esc(job.company) + '</span>\
        </td>\
        <td class="jobs-location">' + esc(job.location) + '</td>\
        <td><span class="jobs-work-type">' + esc(job.work_type || "—") + '</span></td>\
        <td class="jobs-status-cell">\
          <select class="jobs-status-select ' + statusClass(curStatus) + '" data-job-id="' + esc(job.job_id) + '" onchange="window.__updateJobStatus(this.dataset.jobId, this.value)">' +
            STATUSES.map(function(s){ return '<option value="' + s + '"' + (s === curStatus ? ' selected' : '') + '>' + (s ? statusLabel(s) : 'None') + '</option>'; }).join("") +
          '</select>\
        </td>\
        <td class="jobs-salary">' + esc(job.salary || "—") + '</td>\
        <td><span class="jobs-source jobs-source--' + (job.source || "").toLowerCase() + '">' + esc(job.source) + '</span></td>\
        <td>\
          <div class="jobs-score ' + scoreClass(job.match_score) + '">\
            <span class="jobs-score-value">' + job.match_score + '%</span>\
            <span class="jobs-score-label">' + scoreLabel(job.match_score) + '</span>\
            <span class="jobs-score-bar" style="width:' + job.match_score + '%"></span>\
            <div class="jobs-score-detail">' + detailHtml + '</div>\
          </div>\
        </td>\
        <td class="jobs-date">' + timeAgo(job.posted_date) + '</td>\
        <td class="jobs-skills-cell"><div class="jobs-skills-list">' +
          (keySkills.length > 0
            ? keySkills.map(function(s){return '<span class="jobs-skill-tag">' + esc(s) + '</span>';}).join("")
            : '<span class="jobs-no-skills">—</span>') +
        '</div></td>\
        <td class="jobs-matched-cell"><div class="jobs-skills-list">' +
          (skills.length > 0
            ? skills.slice(0, 4).map(function(s){return '<span class="jobs-skill-tag matched">' + esc(s) + '</span>';}).join("")
            : profile && profile.has_cv ? '<span class="jobs-no-skills">No matches</span>' : '<span class="jobs-no-skills">Upload CV</span>') +
        '</div></td>\
        <td class="jobs-gap-cell"><div class="jobs-skills-list">' +
          (gap.length > 0
            ? gap.slice(0, 4).map(function(s){return '<span class="jobs-skill-tag gap">' + esc(s) + '</span>';}).join("")
            : profile && profile.has_cv ? '<span class="jobs-no-skills">None</span>' : '<span class="jobs-no-skills">Upload CV</span>') +
        '</div></td>\
        <td class="jobs-company-url-cell">' +
          (job.company_url ? '<a href="' + esc(job.company_url) + '" target="_blank" rel="noopener" class="jobs-company-link">Link</a>' : '<span class="jobs-no-skills">—</span>') +
        '</td>\
        <td class="jobs-hiring-manager">' + esc(job.hiring_manager || "—") + '</td>\
      </tr>';
    }).join("");
  }

  window.__updateJobStatus = updateStatus;

  function buildWidget() {
    return '\
    <div class="jobs-widget">\
      <div class="jobs-head">\
        <div class="jobs-head-left">\
          <h3 class="jobs-head-title">Smart Job Scanner</h3>\
          <div class="jobs-head-meta">\
            <span class="jobs-stat"><strong id="jobsCount">0</strong> matches</span>\
            <span class="jobs-stat-sep">&middot;</span>\
            <span class="jobs-stat">Avg match <strong id="jobsAvg">0%</strong></span>\
          </div>\
        </div>\
        <div class="jobs-head-right">\
          <button class="btn btn-primary btn-sm jobs-refresh" onclick="window.__jobsTriggerScrape?.()">Refresh Jobs</button>\
        </div>\
      </div>\
      <div class="jobs-profile-bar">\
        <div class="jobs-profile-left">\
          <span class="jobs-profile-label">CV Profile:</span>\
          <span id="profileStatus"></span>\
        </div>\
        <div class="jobs-profile-right">\
          <label class="jobs-cv-btn-wrapper">\
            <span class="btn btn-sm btn-outline">Upload CV</span>\
            <input type="file" id="cvUploadInput" accept=".pdf,.docx,.doc" hidden />\
          </label>\
        </div>\
      </div>\
      <div class="jobs-filters-bar">\
        <div class="jobs-filter-group"><label>City</label><select id="filterCity" class="jobs-filter-select"><option value="">All</option><option value="london">London</option><option value="reading">Reading</option><option value="bristol">Bristol</option><option value="exeter">Exeter</option><option value="bath">Bath</option><option value="cheltenham">Cheltenham</option></select></div>\
        <div class="jobs-filter-group"><label>Work Type</label><select id="filterWorkType" class="jobs-filter-select"><option value="">All</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">On-site</option></select></div>\
        <div class="jobs-filter-group"><label>Seniority</label><select id="filterSeniority" class="jobs-filter-select"><option value="">All</option><option value="high">Manager/Director/Lead/Senior</option><option value="mid">Analyst/Specialist/Associate</option></select></div>\
        <div class="jobs-filter-group"><label>Keyword</label><input id="filterKeyword" type="text" class="jobs-filter-input" placeholder="e.g. marketing ops" /></div>\
        <div class="jobs-filter-group"><label>Country</label><select id="filterCountry" class="jobs-filter-select"><option value="">All</option><option value="uk">UK</option><option value="worldwide">Worldwide</option></select></div>\
        <div class="jobs-filter-group"><label>Salary</label><select id="filterSalary" class="jobs-filter-select"><option value="">Any</option><option value="0-60000">< £60k</option><option value="60000-90000">£60k-90k</option><option value="90000-120000">£90k-120k</option><option value="120000-999999">£120k+</option></select></div>\
        <div class="jobs-filter-group"><label>Date Posted</label><select id="filterPostedSince" class="jobs-filter-select"><option value="all">Any time</option><option value="24h">Last 24 hours</option><option value="3d">Last 3 days</option><option value="1w" selected>Last week</option><option value="older">Over a week</option></select></div>\
        <div class="jobs-filter-group"><label>Match</label><select id="filterMatch" class="jobs-filter-select"><option value="0-100">All</option><option value="75-100">75%+</option><option value="50-75">50-75%</option><option value="0-50"><50%</option></select></div>\
        <div class="jobs-filter-group"><label>Source</label><select id="filterSource" class="jobs-filter-select"><option value="all">All</option></select></div>\
        <div class="jobs-filter-group"><label class="jobs-cv-toggle"><input type="checkbox" id="cvCompareToggle" /> CV Compare</label></div>\
      </div>\
      <div class="jobs-loading hidden" id="jobsLoading"><div class="jobs-loading-spinner"></div><span>Scanning job boards...</span></div>\
      <div class="jobs-table-wrap">\
        <table class="jobs-table">\
          <thead><tr>\
            <th>Role</th><th>Location</th><th>Work Type</th><th>Status</th><th>Salary</th><th>Source</th><th>Match</th><th>Posted</th><th>Key Skills</th><th>Matched Skills</th><th>Skills Gap</th><th>Company URL</th><th>Hiring Manager</th>\
          </tr></thead>\
          <tbody id="jobsTbody"><tr><td colspan="13" class="jobs-empty">Loading jobs...</td></tr></tbody>\
        </table>\
      </div>\
      <div class="jobs-foot">\
        <span class="jobs-foot-text">Powered by LinkedIn &middot; RevOps Roles &middot; Indeed &middot; CV-Library &middot; Adzuna</span>\
        <span class="jobs-foot-text jobs-foot-updated" id="jobsUpdated"></span>\
      </div>\
    </div>';
  }

  function init() {
    var m = document.querySelector("[data-jobs-widget]");
    if (!m) return;
    m.innerHTML = buildWidget();

    // Restore saved filter values into the filters object
    loadFilters();

    tbodyEl = document.getElementById("jobsTbody");
    countEl = document.getElementById("jobsCount");
    avgEl = document.getElementById("jobsAvg");
    loadingEl = document.getElementById("jobsLoading");
    sourceSelect = document.getElementById("filterSource");
    profileStatusEl = document.getElementById("profileStatus");
    cvCompareToggle = document.getElementById("cvCompareToggle");

    // Restore form element values from saved filters
    restoreFormFromFilters();

    var filterIds = ["filterCity","filterWorkType","filterSeniority","filterKeyword","filterCountry","filterSalary","filterPostedSince","filterMatch","filterSource"];
    var filterMap = {filterCity:"city",filterWorkType:"work_type",filterSeniority:"seniority",filterKeyword:"keyword",filterCountry:"country",filterSalary:null,filterPostedSince:"posted_since",filterMatch:null,filterSource:"source"};

    filterIds.forEach(function(id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("change", function() {
        if (id === "filterSalary") {
          var v = el.value;
          if (!v) { filters.salary_min = ""; filters.salary_max = ""; }
          else { var sp = v.split("-"); filters.salary_min = sp[0] || ""; filters.salary_max = sp[1] || ""; }
        } else if (id === "filterMatch") {
          var sp = el.value.split("-");
          filters.min_score = parseFloat(sp[0]) || 0;
          filters.max_score = parseFloat(sp[1]) || 100;
        } else { filters[filterMap[id]] = el.value; }
        saveFilters();
        fetchJobs();
      });
    });

    var kw = document.getElementById("filterKeyword");
    if (kw) kw.addEventListener("input", debounce(function(){filters.keyword=kw.value;saveFilters();fetchJobs();},400));

    var cvI = document.getElementById("cvUploadInput");
    if (cvI) cvI.addEventListener("change", function(){if(cvI.files&&cvI.files[0]){uploadCV(cvI.files[0]);cvI.value="";}});

    if (cvCompareToggle) {
      cvCompareToggle.addEventListener("change", function() { saveFilters(); fetchJobs(); });
      // Restore CV Compare toggle
      var cvSaved = filters.cv_compare;
      if (cvSaved === true || cvSaved === "true") cvCompareToggle.checked = true;
    }

    window.__jobsTriggerScrape = triggerScrape;
    replayDismissedToServer().then(function() {
      fetchSources(); fetchProfile(); fetchStats(); fetchJobs();
    });
  }

  function debounce(fn, ms) { var t; return function(){var a=arguments,self=this;clearTimeout(t);t=setTimeout(function(){fn.apply(self,a);},ms);}; }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();