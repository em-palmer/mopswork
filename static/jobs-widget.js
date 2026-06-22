/**
 * MOpsWork — Job Scanner Widget
 * Fetches live job listings with Status column (4th), compact layout.
 */

(function () {
  "use strict";

  const API_BASE = "http://localhost:8003";
  const STATUSES = ["", "applied", "interviewing", "offer", "withdrawn", "rejected", "not_applicable"];

  let allJobs = [];
  let stats = null;
  let profile = null;
  const filters = {
    min_score: 0, max_score: 100, source: "all",
    city: "", work_type: "", seniority: "", keyword: "",
    country: "", salary_min: "", salary_max: "",
    posted_since: "",
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
  function timeAgo(ds) {
    if (!ds) return "";
    const d = new Date(ds);
    if (isNaN(d.getTime())) return "";
    const dy = Math.floor((Date.now() - d.getTime()) / 86400000);
    if (dy === 0) return "Today";
    if (dy === 1) return "Yesterday";
    if (dy < 7) return dy + "d ago";
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  }
  function esc(s) {
    if (!s) return "";
    const d = document.createElement("div"); d.textContent = s; return d.innerHTML;
  }

  async function updateStatus(jobId, newStatus) {
    const fd = new URLSearchParams();
    fd.set("status", newStatus);
    try {
      await fetch(API_BASE + "/api/applications/" + encodeURIComponent(jobId), {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: fd.toString(),
      });
    } catch (err) { console.error("Status update failed:", err); }
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
      allJobs = await r.json();
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

  async function fetchProfile() {
    try {
      const r = await fetch(API_BASE + "/api/profile");
      if (!r.ok) return;
      profile = await r.json();
      updateProfileUI();
    } catch {}
  }

  async function triggerScrape() {
    var btn = document.querySelector(".jobs-refresh");
    if (btn) { btn.disabled = true; btn.textContent = "Scanning..."; }
    try { await fetch(API_BASE + "/api/scrape", { method: "POST" }); await Promise.all([fetchJobs(), fetchStats()]); }
    catch (e) { console.error(e); }
    finally { if (btn) { btn.disabled = false; btn.textContent = "Refresh Jobs"; } }
  }

  async function uploadCV(file, name) {
    var fd = new FormData();
    fd.append("file", file);
    fd.append("name", name || file.name);
    try {
      var r = await fetch(API_BASE + "/api/profile/upload", { method: "POST", body: fd });
      if (!r.ok) throw new Error("Upload failed: " + r.status);
      profile = await r.json();
      updateProfileUI();
      if (cvCompareToggle) cvCompareToggle.checked = true;
      fetchJobs();
    } catch (e) { console.error(e); alert("CV upload failed. Use PDF or DOCX."); }
  }

  async function deleteProfile() {
    try { await fetch(API_BASE + "/api/profile", { method: "DELETE" }); profile = null; updateProfileUI(); fetchJobs(); } catch {}
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
    if (countEl) countEl.textContent = allJobs.length.toLocaleString();
    if (avgEl && allJobs.length > 0) {
      var sum = 0;
      for (var i = 0; i < allJobs.length; i++) sum += allJobs[i].match_score || 0;
      avgEl.textContent = Math.round(sum / allJobs.length) + "%";
    } else if (avgEl) {
      avgEl.textContent = "0%";
    }
    if (allJobs.length === 0) {
      tbodyEl.innerHTML = '<tr class="jobs-empty"><td colspan="13">No matching jobs found.</td></tr>';
      return;
    }

    tbodyEl.innerHTML = allJobs.map(function(job) {
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
        <div class="jobs-filter-group"><label>Date Posted</label><select id="filterPostedSince" class="jobs-filter-select"><option value="">Any time</option><option value="24h">Last 24 hours</option><option value="3d">Last 3 days</option><option value="1w">Last week</option><option value="older">Over a week</option></select></div>\
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
        <span class="jobs-foot-text">Powered by LinkedIn &middot; RevOpsRoles &middot; RemoteOK &middot; WeWorkRemotely &middot; Jobicy &middot; Adzuna</span>\
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
    fetchSources(); fetchProfile(); fetchStats(); fetchJobs();
  }

  function debounce(fn, ms) { var t; return function(){var a=arguments,self=this;clearTimeout(t);t=setTimeout(function(){fn.apply(self,a);},ms);}; }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();