/* Candidate Job Portal: static/js/jobs.js
   Fetches active jobs from /api/jobs/ and renders cards.
   "Apply" opens a modal; submitting it saves the candidate's profile
   details — including an optional resume/CV file — via
   /api/profiles/me/ (multipart/form-data), then creates an Application
   via /api/applications/ (JSON). */

const HOURS_PER_MONTH = 208; // 26 days x 8 hours — used to show an indicative monthly salary
const MAX_RESUME_BYTES = 5 * 1024 * 1024; // 5MB, must match the backend limit
const isAuthenticated = document.body.dataset.auth === "1";

let currentJobId = null;
let currentJobTitle = "";

function jobCard(job) {
  const monthly = formatPKR(Number(job.hourly_rate) * HOURS_PER_MONTH);
  const hourly = formatPKR(job.hourly_rate);
  return `
    <div class="card">
      <h3>${esc(job.title)}</h3>
      <div class="meta">
        <span class="chip">${esc(job.department)}</span>
        <span class="chip shift">${label(job.shift)} shift</span>
      </div>
      <div class="muted">📍 ${esc(job.location)}</div>
      <div class="salary">
        <span class="amount">${monthly} <span style="font-weight:500;font-size:.75rem;color:var(--muted)">/ month (approx.)</span></span>
        <span class="hourly">${hourly} / hour</span>
      </div>
      <p class="desc">${esc(job.description)}</p>
      ${job.required_certifications ? `<div class="muted">Requires: ${esc(job.required_certifications)}</div>` : ""}
      <div class="row">
        <button class="primary" data-apply="${job.id}" data-title="${esc(job.title)}">Apply now</button>
      </div>
    </div>`;
}

async function loadJobs(query = "") {
  const box = $("#jobs");
  box.innerHTML = '<p class="muted">Loading jobs…</p>';
  try {
    const jobs = list(await api(`/jobs/?search=${encodeURIComponent(query)}`));
    box.innerHTML = jobs.length
      ? `<div class="grid">${jobs.map(jobCard).join("")}</div>`
      : '<p class="muted">No open positions match your search right now.</p>';
  } catch (err) {
    box.innerHTML = `<p class="err">${esc(err.message)}</p>`;
  }
}

function openApplyModal(id, title) {
  if (!isAuthenticated) {
    window.location.href = `/api-auth/login/?next=${encodeURIComponent(window.location.pathname)}`;
    return;
  }
  currentJobId = id;
  currentJobTitle = title;
  $("#apply-title").textContent = title;
  $("#job-id").value = id;
  $("#form-msg").textContent = "";
  $("#apply-modal").showModal();
}

$("#jobs").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-apply]");
  if (!btn) return;
  openApplyModal(btn.dataset.apply, btn.dataset.title);
});

$("#q").addEventListener("input", debounce((e) => loadJobs(e.target.value), 350));

$("#apply-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const msg = $("#form-msg");
  const submitBtn = form.querySelector('button[type="submit"]');
  msg.textContent = "";

  const resumeFile = form.resume.files[0];
  if (resumeFile) {
    if (resumeFile.size > MAX_RESUME_BYTES) {
      msg.textContent = "Resume file must be under 5MB.";
      return;
    }
    if (!/\.(pdf|docx?)$/i.test(resumeFile.name)) {
      msg.textContent = "Resume must be a PDF or Word document (.pdf, .doc, .docx).";
      return;
    }
  }

  submitBtn.disabled = true;
  try {
    // 1) Save/update the candidate's profile details (+ resume, if attached)
    const profileData = new FormData();
    profileData.append("phone_number", form.phone_number.value);
    profileData.append("address", form.address.value);
    profileData.append("preferred_shift", form.preferred_shift.value);
    profileData.append("certifications", form.certifications.value);
    profileData.append("experience_years", form.experience_years.value || "0");
    if (resumeFile) profileData.append("resume", resumeFile);

    await api("/profiles/me/", { method: "PATCH", body: profileData, isForm: true });

    // 2) Submit the application for this job
    await api("/applications/", { method: "POST", body: { job: Number(currentJobId) } });

    $("#apply-modal").close();
    form.reset();
    toast(`Application submitted for "${currentJobTitle}"!`);
  } catch (err) {
    msg.textContent = err.message;
  } finally {
    submitBtn.disabled = false;
  }
});

loadJobs();