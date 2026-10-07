/* HR Recruiter Dashboard: static/js/hr_dashboard.js
   Two tabs:
   1. Applications — fetch /api/applications/, filter by status, change
      status via a per-row dropdown (PATCH /api/applications/{id}/).
   2. Manage Jobs — fetch/create/activate/deactivate/delete jobs via
      /api/jobs/ (full CRUD, staff-only per the API's permissions). */

const STATUSES = ["applied", "practical_test", "medical_check", "hired", "rejected"];
const SHIFTS = ["day", "night", "rotating", "any"];

/* ---------------- Tabs ---------------- */
$$(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab-btn").forEach((b) => b.classList.toggle("on", b === btn));
    $("#tab-applications").hidden = btn.dataset.tab !== "applications";
    $("#tab-jobs").hidden = btn.dataset.tab !== "jobs";
    if (btn.dataset.tab === "jobs") loadJobsManage();
  });
});

/* ---------------- Applications ---------------- */
let appsById = {}; // cache so the AI modal can look up full detail without refetching

function statusSelect(current) {
  const options = STATUSES.map(
    (s) => `<option value="${s}" ${s === current ? "selected" : ""}>${label(s)}</option>`
  ).join("");
  return `<select>${options}</select>`;
}

// Bootstrap badge classes per the spec: green >=80, yellow 50-79, red <50.
// A resume was never uploaded with this application (ai_summary empty and
// score still at its default 0) is shown as a neutral "Not analyzed" badge
// instead of a misleading red 0%.
function matchBadge(app) {
  const analyzed = Boolean(app.ai_summary);
  if (!analyzed) return '<span class="badge bg-secondary">Not analyzed</span>';
  const score = app.ai_match_score ?? 0;
  let cls = "bg-danger";
  if (score >= 80) cls = "bg-success";
  else if (score >= 50) cls = "bg-warning text-dark";
  return `<span class="badge ${cls}">${score}%</span>`;
}

function appRow(app) {
  const p = app.candidate_profile;
  const resumeUrl = app.resume || (p && p.resume_url);
  const candidateExtra = p
    ? `<div class="muted">${esc(p.phone_number || "—")} · ${p.experience_years} yr(s) exp · prefers ${label(p.preferred_shift)}</div>
       ${resumeUrl ? `<a href="${esc(resumeUrl)}" target="_blank" rel="noopener">📄 View CV</a>` : '<span class="muted">No CV uploaded</span>'}`
    : "";
  return `
    <tr data-id="${app.id}">
      <td data-label="Candidate">
        <b>${esc(app.candidate.full_name)}</b>
        <div class="muted">${esc(app.candidate.email)}</div>
        ${candidateExtra}
      </td>
      <td data-label="Job">
        ${esc(app.job_detail.title)}
        <div class="muted">${esc(app.job_detail.department)}</div>
      </td>
      <td data-label="Applied">${new Date(app.applied_at).toLocaleDateString()}</td>
      <td data-label="Status">
        <span class="badge ${app.status}" style="margin-right:8px">${label(app.status)}</span>
        ${statusSelect(app.status)}
      </td>
      <td data-label="AI Match Score">${matchBadge(app)}</td>
      <td data-label="Safety Questions">
        <button type="button" class="btn btn-sm btn-outline-primary"
                data-bs-toggle="modal" data-bs-target="#safetyModal"
                data-app-id="${app.id}">View Safety Questions</button>
      </td>
    </tr>`;
}

function populateStatusFilter() {
  const sel = $("#status-filter");
  sel.innerHTML =
    `<option value="">All statuses</option>` +
    STATUSES.map((s) => `<option value="${s}">${label(s)}</option>`).join("");
}

async function loadApplications(status = "") {
  const tbody = $("#rows");
  tbody.innerHTML = `<tr><td colspan="6" class="muted">Loading…</td></tr>`;
  try {
    const apps = list(await api(`/applications/?status=${status}`));
    appsById = Object.fromEntries(apps.map((a) => [a.id, a]));
    $("#count").textContent = `${apps.length} application(s)`;
    tbody.innerHTML = apps.length
      ? apps.map(appRow).join("")
      : `<tr><td colspan="6" class="muted">No applications found.</td></tr>`;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="err">${esc(err.message)}</td></tr>`;
  }
}

$("#status-filter").addEventListener("change", (e) => loadApplications(e.target.value));

$("#rows").addEventListener("change", async (e) => {
  const select = e.target.closest("select");
  if (!select) return;
  const tr = select.closest("tr");
  const id = tr.dataset.id;
  const newStatus = select.value;
  const badge = tr.querySelector(".badge");

  select.disabled = true;
  try {
    await api(`/applications/${id}/`, { method: "PATCH", body: { status: newStatus } });
    badge.textContent = label(newStatus);
    badge.className = `badge ${newStatus}`;
    toast("Status updated");
  } catch (err) {
    toast(err.message, true);
    loadApplications($("#status-filter").value);
  } finally {
    select.disabled = false;
  }
});

// The modal's trigger button carries Bootstrap's own data-bs-toggle/target
// attributes, so Bootstrap opens it automatically — we just need to fill in
// its content before that happens.
$("#rows").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-app-id]");
  if (!btn) return;
  fillSafetyModal(appsById[btn.dataset.appId]);
});

function fillSafetyModal(app) {
  if (!app) return;
  $("#safety-modal-subtitle").textContent = `${app.candidate.full_name} — ${app.job_detail.title}`;

  // ai_screening_questions is stored server-side as a JSON-encoded string
  // (TextField), so it must be parsed back into an array here.
  let questions = [];
  try {
    questions = JSON.parse(app.ai_screening_questions || "[]");
  } catch (err) {
    questions = [];
  }

  $("#safety-questions-list").innerHTML = questions.length
    ? questions.map((q) => `<li class="mb-2">${esc(q)}</li>`).join("")
    : '<li class="text-muted">No safety questions generated yet — this application has no resume to analyze.</li>';
}

/* ---------------- Manage Jobs ---------------- */
function jobManageCard(job) {
  return `
    <div class="card">
      <h3>${esc(job.title)} ${job.is_active ? "" : '<span class="badge off">Inactive</span>'}</h3>
      <div class="meta">
        <span class="chip">${esc(job.department)}</span>
        <span class="chip shift">${label(job.shift)} shift</span>
      </div>
      <div class="muted">📍 ${esc(job.location)}</div>
      <div class="salary"><span class="amount">${formatPKR(job.hourly_rate)}<span style="font-weight:500;font-size:.75rem;color:var(--muted)"> /hour</span></span></div>
      <p class="desc">${esc(job.description)}</p>
      <div class="muted">${job.applications_count} applicant(s)</div>
      <div class="row">
        <button data-toggle="${job.id}" data-on="${job.is_active ? 0 : 1}">${job.is_active ? "Deactivate" : "Activate"}</button>
        <button class="danger" data-delete="${job.id}" style="color:var(--bad)">Delete</button>
      </div>
    </div>`;
}

async function loadJobsManage() {
  const box = $("#jobs-manage");
  box.innerHTML = '<p class="muted">Loading…</p>';
  try {
    const jobs = list(await api("/jobs/")); // staff see all jobs, active + inactive
    $("#job-count").textContent = `${jobs.length} job(s)`;
    box.innerHTML = jobs.length
      ? jobs.map(jobManageCard).join("")
      : '<p class="muted">No jobs posted yet — use the form above.</p>';
  } catch (err) {
    box.innerHTML = `<p class="err">${esc(err.message)}</p>`;
  }
}

$("#job-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("#job-form-msg");
  msg.textContent = "";
  const data = Object.fromEntries(new FormData(e.target));
  try {
    await api("/jobs/", { method: "POST", body: data });
    e.target.reset();
    toast("Job posted!");
    loadJobsManage();
  } catch (err) {
    msg.textContent = err.message;
  }
});

$("#jobs-manage").addEventListener("click", async (e) => {
  const toggleBtn = e.target.closest("[data-toggle]");
  const deleteBtn = e.target.closest("[data-delete]");
  try {
    if (toggleBtn) {
      await api(`/jobs/${toggleBtn.dataset.toggle}/`, {
        method: "PATCH",
        body: { is_active: toggleBtn.dataset.on === "1" },
      });
      loadJobsManage();
    }
    if (deleteBtn && confirm("Delete this job and all its applications?")) {
      await api(`/jobs/${deleteBtn.dataset.delete}/`, { method: "DELETE" });
      toast("Job deleted");
      loadJobsManage();
    }
  } catch (err) {
    toast(err.message, true);
  }
});

/* ---------------- Init ---------------- */
populateStatusFilter();
loadApplications();