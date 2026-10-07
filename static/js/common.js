/* Shared helpers used by jobs.js and hr_dashboard.js.
   Auth here is Django's normal session login (via /api-auth/login/),
   so every fetch() just needs credentials + a CSRF header on unsafe methods. */

const API = "/api";

function getCookie(name) {
  const match = document.cookie.match("(?:^|; )" + name + "=([^;]*)");
  return match ? decodeURIComponent(match[1]) : null;
}

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function label(s) {
  return String(s ?? "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function list(data) {
  return data && data.results ? data.results : (data || []);
}

// Format a number as PKR currency, e.g. formatPKR(150000) -> "PKR 150,000"
function formatPKR(amount) {
  const n = Number(amount) || 0;
  return "PKR " + n.toLocaleString("en-PK", { maximumFractionDigits: 0 });
}

function errText(data) {
  if (!data || typeof data !== "object") return "";
  return Object.entries(data)
    .filter(([k]) => k !== "detail" || Object.keys(data).length === 1)
    .map(([k, v]) => {
      const msg = Array.isArray(v) ? v.join(" ") : (typeof v === "object" ? errText(v) : v);
      return k === "detail" ? msg : `${k}: ${msg}`;
    })
    .join(" | ");
}

async function api(path, { method = "GET", body, isForm = false } = {}) {
  const headers = {};
  if (method !== "GET") headers["X-CSRFToken"] = getCookie("csrftoken");
  // For FormData (file uploads) the browser sets Content-Type itself,
  // including the multipart boundary — never set it manually here.
  if (!isForm) headers["Content-Type"] = "application/json";

  const res = await fetch(API + path, {
    method,
    headers,
    credentials: "same-origin",
    body: isForm ? body : (body !== undefined ? JSON.stringify(body) : undefined),
  });

  const data = res.status === 204 ? null : await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(errText(data) || `Request failed (${res.status})`);
  return data;
}

let toastTimer;
function toast(message, isError = false) {
  const el = $("#toast");
  if (!el) return;
  el.textContent = message;
  el.className = "show" + (isError ? " bad" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.className = ""), 3200);
}

function debounce(fn, ms = 300) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}