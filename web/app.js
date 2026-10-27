/* SLT AI Employee - the pages for the HR officer and the Interviewer.
   Plain JavaScript, no framework. Every value from the server is escaped before it is shown. */
"use strict";

// ---------------------------------------------------------------- helpers
const $ = (s, el = document) => el.querySelector(s);
const view = $("#view");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (n, cls = "") => `<svg class="ic ${cls}" aria-hidden="true"><use href="icons.svg#i-${n}"/></svg>`;
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private window */ } },
};
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const AI_ACTORS = new Set(["Recruiter", "Coordinator", "Onboarding", "Chief of staff"]);

let ROLE = store.get("slt-role", "hr");
if (!["hr", "interviewer"].includes(ROLE)) ROLE = "hr";
let STATE = null;
let lastHTML = "";
let current = { page: "", arg: "" };
const UI = { showCv: false, showRuns: false, editDraft: null, editEmail: false, candFilter: "", candQuery: "",
             repliesTab: "waiting", showAll: "", files: [], uploadResults: null, areas: null,
             cvAnswer: null, cvLoading: false };

async function api(path, { method = "GET", body, form } = {}) {
  const opt = { method, headers: { "X-Role": ROLE } };
  if (form) opt.body = form;
  else if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  let data = null;
  try { data = await r.json(); } catch { /* no body */ }
  if (!r.ok) throw new Error((data && data.detail) || `The server answered with error ${r.status}.`);
  return data;
}

function toast(msg, bad = false) {
  const t = document.createElement("div");
  t.className = "toast" + (bad ? " bad" : "");
  t.innerHTML = icon(bad ? "triangle-alert" : "circle-check", "sm") + `<span>${esc(msg)}</span>`;
  $("#toasts").appendChild(t);
  while ($("#toasts").children.length > 3) $("#toasts").firstChild.remove();
  setTimeout(() => t.remove(), bad ? 7000 : 4500);
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
function dateBox(iso) {
  const d = new Date(iso || Date.now());
  return `<div class="datebox"><div><small>${MONTHS[d.getMonth()] || ""}</small><b>${isNaN(d) ? "-" : d.getDate()}</b></div></div>`;
}
const chip = (c) => `<span class="chip ${esc(c.chip)}">${esc(c.status_label)}</span>`;
function sourceTag(text) {
  if (!text) return "";
  const t = text.toLowerCase();
  const cls = t.includes("hr officer") || t.includes("interviewer") ? "person" : (t.includes("rule") || t.includes("template") || t.includes("standard")) ? "rules" : "ai";
  const ic = cls === "person" ? "user" : cls === "ai" ? "sparkles" : "list-checks";
  return `<span class="who-tag ${cls}">${icon(ic, "sm")}${esc(text)}</span>`;
}
function actorTag(actor) {
  return AI_ACTORS.has(actor)
    ? `<span class="who-tag ai">${icon("bot", "sm")}AI ${esc(actor)}</span>`
    : `<span class="who-tag person">${icon("user", "sm")}${esc(actor)}</span>`;
}
const scoreColor = (s) => (s == null ? "gray" : s >= 60 ? "green" : s >= 50 ? "amber" : "red");
const scoreChip = (s) => (s == null ? `<span class="chip gray">No score</span>` : `<span class="chip ${scoreColor(s)}">Score ${esc(s)}/100</span>`);
const initials = (name) => (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
const empty = (text, ic = "inbox") => `<div class="empty">${icon(ic)}<div>${esc(text)}</div></div>`;

function title(t) { $("#page-title").textContent = t; document.title = `${t} - SLT AI Employee`; }
function setView(html) {
  if (html === lastHTML) return;
  const y = window.scrollY;
  lastHTML = html;
  view.innerHTML = html;
  window.scrollTo(0, y);
}
function busy() {
  const a = document.activeElement;
  return $("#dialog").open || !$("#role-menu").hidden || document.hidden ||
    (a && ["INPUT", "TEXTAREA", "SELECT"].includes(a.tagName)) || UI.editDraft !== null || UI.editEmail || UI.cvLoading;
}

// ---------------------------------------------------------------- dialogs
function openDialog(html) {
  $("#dialog-body").innerHTML = html;
  const d = $("#dialog");
  if (!d.open) d.showModal();
  const f = d.querySelector("input, textarea, select");
  if (f) f.focus();
}
function closeDialog() { $("#dialog").close(); }
function confirmBox({ heading, text, ok = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    openDialog(`<h3>${esc(heading)}</h3><p class="muted">${esc(text)}</p>
      <div class="actions"><button class="btn" data-dlg="no">Cancel</button>
      <button class="btn ${danger ? "danger" : "primary"}" data-dlg="yes">${esc(ok)}</button></div>`);
    const d = $("#dialog");
    const done = (v) => { d.removeEventListener("close", onClose); closeDialog(); resolve(v); };
    const onClose = () => resolve(false);
    d.addEventListener("close", onClose, { once: true });
    d.querySelector('[data-dlg="yes"]').onclick = () => done(true);
    d.querySelector('[data-dlg="no"]').onclick = () => done(false);
  });
}

// ---------------------------------------------------------------- frame: role, nav, top bar
const NAV = {
  hr: [
    ["dashboard", "Dashboard", "layout-dashboard"], ["add", "Add CV", "file-plus"], ["candidates", "Candidates", "users"],
    ["review", "Review queue", "clipboard-check", "review"], ["replies", "Replies", "mail", "release"], ["areas", "Areas", "layers"],
    null, ["team", "AI team", "bot"],
  ],
  interviewer: [["interviews", "Interviews", "calendar-check", "interview"], null, ["team", "AI team", "bot"]],
};
const HOME = { hr: "#/dashboard", interviewer: "#/interviews" };

function renderFrame() {
  const t = STATE ? STATE.tiles : {};
  $("#sidebar").innerHTML = NAV[ROLE].map((n) => {
    if (!n) return `<div class="nav-sep"></div>`;
    const [key, label, ic, countKey] = n;
    const count = countKey && t[countKey] ? `<span class="count">${esc(t[countKey])}</span>` : "";
    const active = current.page === key || (key === "candidates" && current.page === "candidate") || (key === "interviews" && current.page === "interview");
    return `<a class="nav-item ${active ? "active" : ""}" href="#/${key}" title="${esc(label)}">${icon(ic)}<span>${esc(label)}</span>${count}</a>`;
  }).join("") + `<div class="side-foot">${sideFoot()}</div>`;
  $("#avatar").textContent = ROLE === "hr" ? "HR" : "IN";
  $("#who-name").textContent = ROLE === "hr" ? "HR Officer" : "Interviewer";
  $("#who-sub").textContent = ROLE === "hr" ? "Reviewer - switch role" : "Interview panel - switch role";
  document.querySelectorAll("[data-tick]").forEach((el) => { el.style.visibility = el.dataset.tick === ROLE ? "visible" : "hidden"; });
}
function sideFoot() {
  if (!STATE) return "";
  const working = Object.values(STATE.team).find((x) => x.state === "working");
  const status = STATE.paused ? "Paused" : working ? `${esc(working.name)} is working` : "Waiting for work";
  return `AI team: <b>${status}</b><br>Emails are drafted only, never sent.`;
}
function renderTop() {
  if (!STATE) return;
  const m = STATE.model;
  const down = !m.ok || (STATE.notice && STATE.notice.text);
  $("#model-pill").innerHTML = `<i class="dot ${down ? "bad" : "ok"}"></i><span>${down ? "Model not running" : "Model: " + esc(m.model)}</span>`;
  $("#model-pill").title = (STATE.notice && STATE.notice.text) || m.detail || "";
  const n = ROLE === "hr" ? STATE.tiles.review + STATE.tiles.release : STATE.tiles.interview;
  const b = $("#bell-badge");
  b.hidden = !n;
  b.textContent = n;
}
async function refreshState() {
  try { STATE = await api("/api/state"); } catch { return; }
  renderTop();
  renderFrame();
}

$("#user-btn").onclick = (e) => {
  e.stopPropagation();
  const m = $("#role-menu");
  m.hidden = !m.hidden;
  $("#user-btn").setAttribute("aria-expanded", String(!m.hidden));
};
document.addEventListener("click", (e) => { if (!e.target.closest(".user")) $("#role-menu").hidden = true; });
$("#role-menu").addEventListener("click", (e) => {
  const b = e.target.closest("[data-role]");
  if (!b) return;
  ROLE = b.dataset.role;
  store.set("slt-role", ROLE);
  $("#role-menu").hidden = true;
  toast(`You are now using the system as ${ROLE === "hr" ? "the HR Officer" : "the Interviewer"}.`);
  lastHTML = "";
  location.hash = HOME[ROLE];
  renderFrame();
  renderTop();
});
$("#bell").onclick = () => { location.hash = ROLE === "hr" ? "#/review" : "#/interviews"; };

// ---------------------------------------------------------------- shared pieces
function hero({ kicker, name, initialsText, chips, action }) {
  return `<section class="hero"><div class="hero-avatar"><div>${esc(initialsText)}</div><span class="online"></span></div>
    <div class="grow"><div class="kicker">${esc(kicker)}</div><h1>${esc(name)}</h1><div class="chips">${chips.join("")}</div></div>
    ${action || ""}</section>`;
}
function banner(kind, ic, head, text, action = "") {
  return `<div class="banner ${kind}"><div class="hicon ${kind === "red" ? "red" : kind === "green" ? "green" : kind === "amber" ? "amber" : "blue"}">${icon(ic)}</div>
    <div class="grow"><b>${esc(head)}</b>${text ? `<span class="muted small">${esc(text)}</span>` : ""}</div>${action}</div>`;
}
function cardHead(ic, color, text, extra = "") {
  return `<div class="card-head"><div class="hicon ${color}">${icon(ic)}</div><h2>${esc(text)}</h2><div class="spacer"></div>${extra}</div>`;
}
function modelBanner() {
  if (!STATE) return "";
  const notice = STATE.notice && STATE.notice.text;
  if (STATE.model.ok && !notice) return "";
  return banner("red", "triangle-alert", "The AI employees cannot work: the model server is not running.",
    " Open a second terminal in the project folder and run ./start_model.sh, then wait until it says the server is listening. " + (notice || STATE.model.detail || ""));
}
function mailBlock(d, { showCandidate = false } = {}) {
  const editing = UI.editDraft === d.id;
  const statusChip = d.status === "waiting" ? `<span class="chip amber">Waiting for release</span>` : d.status === "released" ? `<span class="chip green">Released</span>` : `<span class="chip gray">${esc(d.status)}</span>`;
  const notes = (d.check_notes || []).map((n) => `<div class="warn">${icon("triangle-alert", "sm")}<span>${esc(n)}</span></div>`).join("");
  let foot = "";
  if (d.status === "waiting" && ROLE === "hr") {
    foot = editing
      ? `<button class="btn primary" data-act="save-draft" data-id="${d.id}">${icon("check")} Save changes</button><button class="btn" data-act="cancel-edit">Cancel</button>`
      : `<button class="btn primary" data-act="release" data-id="${d.id}" data-name="${esc(d.name)}" data-kind="${esc(d.kind_label)}" ${d.can_release ? "" : "disabled"}>${icon("send")} Release</button>
         <button class="btn" data-act="edit-draft" data-id="${d.id}">${icon("pencil")} Edit</button>
         ${d.can_release ? "" : `<span class="small muted">${esc(d.release_blocker || "The candidate is not at this step now.")}</span>`}`;
  } else if (d.status === "released") {
    foot = `<span class="small muted">${icon("check", "sm")} Released ${esc(fmtTime(d.released_at))}. Saved to data/outbox/${esc(d.file)} (not sent).</span>`;
  }
  const body = editing
    ? `<div class="mail-body"><div class="form-row"><label for="ed-subject">Subject</label><input type="text" id="ed-subject" value="${esc(d.subject)}"></div>
       <div class="form-row"><label for="ed-body">Email</label><textarea id="ed-body" rows="12">${esc(d.body)}</textarea></div></div>`
    : `<div class="mail-body"><b>${esc(d.subject)}</b>\n\n${esc(d.body)}</div>`;
  return `<div class="mail" id="mail-${d.id}">
    <div class="mail-head"><span class="chip blue">${esc(d.kind_label)}</span>${statusChip}${sourceTag(d.written_by)}
      <span class="grow"></span>${showCandidate ? `<a href="#/candidate/${encodeURIComponent(d.app_no)}">${esc(d.app_no)}</a>` : ""}
      <span class="small muted">To: ${esc(d.name || "")} ${d.email ? "&lt;" + esc(d.email) + "&gt;" : "(no email yet)"}</span></div>
    ${notes ? `<div style="padding:12px 18px 0">${notes}</div>` : ""}${body}${foot ? `<div class="mail-foot">${foot}</div>` : ""}</div>`;
}

// ================================================================ HR officer pages
async function pDashboard() {
  title("Dashboard");
  const [s, all] = await Promise.all([api("/api/state"), api("/api/candidates")]);
  STATE = s;
  renderTop(); renderFrame();
  const t = s.tiles;
  const working = Object.values(s.team).find((x) => x.state === "working");
  let next;
  if (t.review) next = banner("amber", "clipboard-check", `${t.review} item(s) need your decision or a quick check.`, " Open the Review queue to see them.", `<a class="btn" href="#/review">Open Review queue ${icon("arrow-right", "sm")}</a>`);
  else if (t.release) next = banner("amber", "mail", `${t.release} email(s) are waiting for your release.`, " Nothing reaches a student until you release it.", `<a class="btn" href="#/replies">Open Replies ${icon("arrow-right", "sm")}</a>`);
  else if (!s.total) next = banner("blue", "info", "No CVs yet.", " Add a CV to start, or load the sample CVs.", `<a class="btn" href="#/add">Add CV ${icon("arrow-right", "sm")}</a>`);
  else next = banner("green", "circle-check", "Nothing needs you right now.", " The AI team is handling the rest.");
  const tiles = [
    ["slate", "New CVs", "file-text", t.new, "Waiting for the Recruiter", "#/candidates/new"],
    ["blue", "Needs your review", "clipboard-check", t.review, "Decisions and notes", "#/review"],
    ["indigo", "Emails to release", "mail", t.release, "Drafted by the AI team", "#/replies"],
    ["purple", "In interview", "calendar-check", t.interview, "Waiting for a result", "#/candidates/interview"],
    ["green", "Selected", "award", t.selected, "Work IDs issued", "#/candidates/selected"],
  ].map(([c, l, ic, n, cap, href]) => `<a class="tile ${c}" href="${href}"><div class="t-head"><div class="t-icon">${icon(ic)}</div>${esc(l)}</div>
      <div class="t-num">${esc(n)}</div><div class="t-cap">${esc(cap)}</div><svg class="ic t-mark" aria-hidden="true"><use href="icons.svg#i-${ic}"/></svg></a>`).join("");
  const team = Object.entries(s.team).map(([k, e], i) => `<div class="row"><div class="emp-icon e${i}" style="width:42px;height:42px;border-radius:12px">${icon(["user-round-search", "calendar-check", "id-card", "activity"][i])}</div>
      <div class="grow"><div class="title">${esc(e.name)}</div><div class="sub">${e.state === "working" ? esc(e.doing) : e.last_run ? "Last run " + esc(fmtTime(e.last_run)) + " - " + esc(e.last_note) : "Waiting for work"}</div></div>
      ${s.paused ? `<span class="chip gray">Paused</span>` : e.state === "working" ? `<span class="chip blue"><i class="dot busy"></i>Working</span>` : `<span class="chip green">Ready</span>`}</div>`).join("");
  // Selected = passed the interview, counted per area
  const passed = {};
  all.filter((c) => c.result === "Pass").forEach((c) => { passed[c.area] = (passed[c.area] || 0) + 1; });
  const areaNames = s.areas_chart.map((a) => a.area);
  Object.keys(passed).forEach((a) => { if (!areaNames.includes(a)) areaNames.push(a); });
  const totalPassed = Object.values(passed).reduce((x, y) => x + y, 0);
  const areaNums = areaNames.length ? `<div class="num-grid"><a class="num-box total" href="#/candidates/selected"><b>${esc(totalPassed)}</b><span>All areas</span></a>
      ${areaNames.map((a) => `<div class="num-box"><b>${esc(passed[a] || 0)}</b><span>${esc(a)}</span></div>`).join("")}</div>` : empty("No areas yet.");
  // End-to-end conversion numbers from application to selection
  const fn = s.funnel || {};
  const funnelSteps = [
    ["Applied", fn.applied ?? s.total],
    ["AI Screened", fn.screened ?? 0],
    ["Shortlisted", fn.shortlisted ?? 0],
    ["Interviewed", fn.interviewed ?? 0],
    ["Selected", fn.selected ?? 0],
  ];
  const funnelHtml = `<div class="num-grid">${funnelSteps.map(([lbl, val], idx) => `<div class="num-box ${idx === 4 ? "total" : ""}"><b>${esc(val)}</b><span>${esc(lbl)}</span></div>`).join("")}</div>`;
  const recent = s.recent.length ? s.recent.slice(0, 5).map((r) => `<${r.app_no ? `a href="#/candidate/${encodeURIComponent(r.app_no)}"` : "div"} class="row">${dateBox(r.at)}
      <div class="grow"><div class="title">${esc(r.text)}</div><div class="sub">${actorTag(r.actor)} ${r.app_no ? esc(r.app_no) + " - " + esc(r.name || "") : ""} - ${esc(fmtTime(r.at))}</div></div></${r.app_no ? "a" : "div"}>`).join("") : empty("Nothing has happened yet.");
  const brief = s.brief ? `<p style="margin:0 0 12px;line-height:1.65">${esc(s.brief.text)}</p><div class="actions">${sourceTag("Chief of staff - " + s.brief.written_by)}<span class="small muted">${esc(fmtTime(s.brief.created_at))}</span></div>`
    : `<p class="muted">The Chief of staff writes a brief every morning at 08:00.</p>`;
  setView(`${hero({ kicker: "Welcome back", name: "HR Officer", initialsText: "HR",
      chips: [`<span class="chip">${icon("users", "sm")} ${esc(s.total)} candidates</span>`,
        `<span class="chip on">${icon("bot", "sm")} AI team: ${s.paused ? "paused" : working ? "working" : "ready"}</span>`,
        `<span class="chip">${icon("shield-check", "sm")} Emails are never sent automatically</span>`],
      action: `<a class="btn primary" href="#/add">${icon("file-plus")} Add CV</a>` })}
    ${modelBanner() ? `<div style="margin-top:24px">${modelBanner()}</div>` : ""}
    <div style="margin-top:24px">${next}</div>
    <div class="tiles" style="margin-top:24px">${tiles}</div>
    <div class="card">${cardHead("message-square-text", "green", "Morning brief", `<button class="btn small" data-act="brief">${icon("refresh-cw", "sm")} Write brief now</button>`)}${brief}</div>
    <div class="grid two">
      <div class="card">${cardHead("chart-column", "blue", "Hiring pipeline funnel", `<span class="hint">End-to-end conversion</span>`)}${funnelHtml}</div>
      <div class="card">${cardHead("award", "green", "Selected candidates by area", `<span class="hint">Passed the interview</span>`)}${areaNums}</div>
    </div>
    <div class="grid two">
      <div class="card">${cardHead("activity", "purple", "Recent activity")}<div class="rows">${recent}</div></div>
      <div class="card">${cardHead("bot", "purple", "AI team", `<a class="btn small" href="#/team">Open AI team</a>`)}<div class="rows">${team}</div></div>
    </div>`);
}

async function pAdd() {
  title("Add CV");
  const files = UI.files;
  const results = UI.uploadResults;
  const resultRows = results ? results.map((r) => r.ok
    ? `<a class="row" href="#/candidate/${encodeURIComponent(r.app_no)}"><span class="chip green">${icon("check", "sm")} Added</span><div class="grow"><div class="title">${esc(r.file)}</div><div class="sub">Application number ${esc(r.app_no)}</div></div>${icon("arrow-right", "sm")}</a>`
    : `<div class="row"><span class="chip red">${icon("x", "sm")} Not added</span><div class="grow"><div class="title">${esc(r.file)}</div><div class="sub">${esc(r.reason)}</div></div></div>`).join("") : "";
  setView(`<div class="card">${cardHead("file-plus", "blue", "Add CVs")}
      <div class="add-grid">
        <div>
          <label class="drop" id="drop" for="file-input">${icon("upload")}<div class="drop-title">Drop CV files here, or click to choose</div>
            <div class="small muted">PDF, Word (.docx) or text files, up to 5 MB each. You can add several at once.</div></label>
          <input type="file" id="file-input" accept=".pdf,.docx,.txt" multiple hidden>
          ${files.length ? `<div class="rows" style="margin-top:16px">${files.map((f, i) => `<div class="row">${icon("file-text")}<div class="grow"><div class="title">${esc(f.name)}</div><div class="sub">${Math.ceil(f.size / 1024)} KB</div></div><button class="btn small" data-act="remove-file" data-i="${i}">${icon("x", "sm")} Remove</button></div>`).join("")}</div>` : ""}
        </div>
        <div class="add-side">
          <div class="form-row"><label for="cv-email">Student's email (optional)</label>
            <input type="email" id="cv-email" placeholder="${files.length > 1 ? "Only for a single CV" : "name@example.com"}" ${files.length > 1 ? "disabled" : ""}>
            <div class="help">If you type it, replies use this address. If you leave it empty, the Recruiter reads it from the CV and you confirm it.</div></div>
          <div class="small muted" style="margin-top:16px">${files.length ? `${files.length} file(s) chosen.` : "No files chosen yet."}</div>
          <div class="actions" style="margin-top:12px"><button class="btn primary" data-act="upload" ${files.length ? "" : "disabled"}>${icon("upload")} Add ${files.length > 1 ? files.length + " CVs" : "CV"}</button>
            ${files.length ? `<button class="btn" data-act="clear-files">Clear</button>` : ""}</div>
        </div>
      </div>
    </div>
      ${results ? `<div class="card">${cardHead("list-checks", "green", "Result")}<div class="rows">${resultRows}</div></div>` : ""}
      <div class="card">${cardHead("info", "purple", "What happens next")}<div class="steps">
        <div><div><b>Recruiter</b><div class="small muted">Reads the CV, chooses the area and scores the match. Every fact is checked against the CV.</div></div></div>
        <div><div><b>You</b><div class="small muted">Decide borderline and low scores, choose areas the AI is unsure about.</div></div></div>
        <div><div><b>Coordinator</b><div class="small muted">Books an interview slot, prepares questions and drafts the invitation for you to release.</div></div></div>
        <div><div><b>Interviewer</b><div class="small muted">Does the interview and enters Pass, Fail or Hold.</div></div></div>
        <div><div><b>Onboarding</b><div class="small muted">Issues the 4-digit work ID and drafts the acceptance email for you to release.</div></div></div></div></div>
      <div class="card">${cardHead("sparkles", "green", "Try it with sample CVs")}<p class="muted small" style="margin-top:0">Seven made-up students in PDF, Word and text files, for demos and testing.</p>
        <button class="btn" data-act="samples">${icon("users")} Load the sample CVs</button></div>`);
  const input = $("#file-input");
  input.onchange = () => { addFiles(input.files); input.value = ""; };
  const drop = $("#drop");
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); addFiles(e.dataTransfer.files); };
}
function addFiles(list) {
  for (const f of list) if (!UI.files.some((x) => x.name === f.name && x.size === f.size)) UI.files.push(f);
  UI.uploadResults = null;
  lastHTML = "";
  pAdd();
}

const FILTERS = [["", "All"], ["selected", "Selected candidates"], ["new", "New"], ["interview", "In interview"], ["closed", "Closed"], ["review", "Needs you"], ["release", "Emails to release"]];
async function pCandidates(arg) {
  title("Candidates");
  // Update the filter when coming from a link (e.g. #/candidates or #/candidates/selected).
  if (arg !== undefined && FILTERS.some((f) => f[0] === arg)) UI.candFilter = arg;
  const selected = UI.candFilter === "selected";
  let rows = await api(`/api/candidates?status=${encodeURIComponent(UI.candFilter)}`);
  const q = UI.candQuery.toLowerCase();
  const shown = q ? rows.filter((c) => [c.name, c.app_no, c.area, c.email].join(" ").toLowerCase().includes(q)) : rows;
  const csvUrl = `/api/candidates.csv?status=${encodeURIComponent(UI.candFilter)}&q=${encodeURIComponent(UI.candQuery)}`;
  const body = shown.length ? `<table class="list"><thead><tr><th>Application</th><th>Student</th><th>Area</th><th>Score</th><th>Status</th><th>Next</th></tr></thead><tbody>
    ${shown.map((c) => `<tr class="click" data-href="#/candidate/${encodeURIComponent(c.app_no)}">
      <td><b>${esc(c.app_no)}</b><div class="small muted">${esc(fmtTime(c.created_at))}</div></td>
      <td><b>${esc(c.name)}</b><div class="small muted">${esc(c.email || "no email yet")}</div></td>
      <td>${c.area ? esc(c.area) : c.suggested_new_area ? `<span class="small muted">Suggested: ${esc(c.suggested_new_area)}</span>` : `<span class="muted">-</span>`}</td>
      <td><b class="mono" style="color:var(--${scoreColor(c.score)}-ink, var(--muted))">${c.score == null ? "-" : esc(c.score)}</b></td>
      <td>${chip(c)} ${c.open_flags ? `<span class="chip amber" title="Notes to check">${icon("triangle-alert", "sm")}${esc(c.open_flags)}</span>` : ""}</td>
      <td class="small muted">${esc(c.next_actor || (c.outcome || "Done"))}</td></tr>`).join("")}</tbody></table>`
    : empty(rows.length ? "No candidate matches your search." : selected ? "No one has passed an interview yet." : "No candidates here.", "users");
  setView(`<div class="card">${cardHead("users", "blue", "Candidates", `<div class="actions"><a class="btn small" href="${csvUrl}">${icon("download", "sm")} Export CSV</a><a class="btn primary" href="#/add">${icon("file-plus")} Add CV</a></div>`)}
    <div class="filters"><div class="seg">${FILTERS.map(([k, l]) => `<button class="${UI.candFilter === k ? "on" : ""}" data-act="filter" data-f="${k}">${esc(l)}</button>`).join("")}</div>
    <div class="search">${icon("search", "sm")}<input type="search" id="cand-q" placeholder="Search name, number, area" value="${esc(UI.candQuery)}"></div></div>${body}</div>`);
  const qi = $("#cand-q");
  qi.oninput = () => { UI.candQuery = qi.value; const pos = qi.selectionStart; lastHTML = ""; pCandidates().then(() => { const n = $("#cand-q"); n.focus(); n.setSelectionRange(pos, pos); }); };
}

function nextStep(c, areas) {
  const areaSelect = (label) => `<select id="area-pick" style="max-width:220px">${areas.filter((a) => a.active).map((a) => `<option ${a.name === c.area ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</select>
      <button class="btn ${label ? "primary" : "small"}" data-act="set-area">${esc(label || "Use this area")}</button>`;
  switch (c.status) {
    case "new": return banner("blue", "hourglass", "The Recruiter will read this CV in a moment.", " The page updates by itself.");
    case "needs_person": return banner("red", "triangle-alert", "This CV could not be read.", " It may be a scanned PDF. Upload it again as Word or text, or try again.",
      `<div class="actions"><button class="btn primary" data-act="retry">${icon("refresh-cw")} Try again</button><button class="btn danger" data-act="close">Close</button></div>`);
    case "needs_area": return banner("amber", "layers", "Choose the internship area for this student.",
      c.suggested_new_area ? ` The AI suggested a new area: "${c.suggested_new_area}". Add it on the Areas page first if you agree.` : " The Recruiter could not choose one with confidence.",
      `<div class="actions">${areaSelect("Save area")}${c.suggested_new_area ? `<a class="btn" href="#/areas/new:${encodeURIComponent(c.suggested_new_area)}">${icon("plus", "sm")} Add "${esc(c.suggested_new_area)}"</a>` : ""}<button class="btn danger" data-act="close">Close</button></div>`);
    case "borderline": return banner("amber", "clipboard-check", `Score ${c.score}/100 is borderline (50 to 59). Please decide.`, "",
      `<div class="actions"><button class="btn primary" data-act="decide" data-d="shortlist">${icon("check")} Shortlist</button><button class="btn" data-act="decide" data-d="not_shortlist">Not shortlisted</button></div>`)
      + `<div class="actions small muted" style="margin-top:10px">Wrong area? ${areaSelect("")}</div>`;
    case "not_shortlisted_check": return banner("amber", "clipboard-check", `Score ${c.score}/100 is below 50. Confirm Not shortlisted?`, " A polite reply is drafted only after you confirm.",
      `<div class="actions"><button class="btn primary" data-act="decide" data-d="confirm">${icon("check")} Confirm Not shortlisted</button><button class="btn" data-act="decide" data-d="shortlist">Shortlist instead</button></div>`)
      + `<div class="actions small muted" style="margin-top:10px">Wrong area? ${areaSelect("")}</div>`;
    case "invite_ready": case "reply_ready": case "hold_note_ready": case "offer_ready":
      return banner("amber", "mail", "An email is waiting for your release.", " Read it below, edit it if needed, then release it.", `<a class="btn" href="#emails" data-act="jump">${icon("arrow-right", "sm")} Go to the email</a>`);
    case "awaiting_result": return banner("blue", "calendar-check", `Waiting for the interviewer's result.`, ` Interview: ${c.interview_label}.`);
    case "on_hold": return banner("amber", "hourglass", "The result is on hold.", " The interviewer will enter Pass or Fail later.");
    case "closed": return banner(c.outcome.startsWith("Selected") ? "green" : "blue", c.outcome.startsWith("Selected") ? "award" : "circle-check", `Closed: ${c.outcome || "done"}.`, "");
    default: return banner("blue", "bot", `The ${c.next_actor} is working on this.`, " The page updates by itself.");
  }
}

function askCvCard(c) {
  if (!c.cv_text) return "";
  return `<div class="card" style="margin-top:24px">${cardHead("sparkles", "blue", "Ask the CV", `<span class="hint">Citation-checked against the CV text</span>`)}
    <div class="actions" style="margin-bottom:12px">
      ${["Summarize key strengths", "What projects did this student build?", "Does the CV mention databases or SQL?", "What cloud or DevOps tools are listed?"].map((q) => `<button class="btn small" data-act="ask-preset" data-q="${esc(q)}" ${UI.cvLoading ? "disabled" : ""}>${esc(q)}</button>`).join("")}
    </div>
    <div class="actions"><input type="text" id="ask-cv-q" placeholder="Ask any question about this candidate's CV..." style="flex:1;min-width:240px" value="${esc(UI.cvAnswer ? UI.cvAnswer.question : "")}"><button class="btn primary" data-act="ask-cv" ${UI.cvLoading ? "disabled" : ""}>${icon("search", "sm")} ${UI.cvLoading ? "Checking CV..." : "Ask CV"}</button></div>
    ${UI.cvAnswer ? `<div class="note" style="margin-top:14px;background:var(--soft);border-color:var(--line)"><div class="grow"><div style="display:flex;gap:8px;align-items:center;margin-bottom:6px"><b>Answer</b>${sourceTag(UI.cvAnswer.source)}</div><div style="line-height:1.6">${esc(UI.cvAnswer.answer)}</div>${UI.cvAnswer.quotes && UI.cvAnswer.quotes.length ? `<div style="margin-top:10px"><div class="label">Exact quotes verified in CV</div>${UI.cvAnswer.quotes.map((qt) => `<div class="quote">"${esc(qt)}"</div>`).join("")}</div>` : ""}</div></div>` : ""}
  </div>`;
}

async function pCandidate(appNo) {
  title("Candidate");
  const [c, areas] = await Promise.all([api(`/api/candidates/${encodeURIComponent(appNo)}`), UI.areas ? Promise.resolve(UI.areas) : api("/api/areas")]);
  UI.areas = areas;
  const p = c.profile || {};
  const list = (items, none) => (items && items.length ? `<ul class="clean">${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<span class="muted">${esc(none)}</span>`);
  const flags = c.flags.filter((f) => f.open);
  const parts = c.score_parts || {};
  const bars = Object.entries(parts).map(([k, v]) => {
    const pct = v.max ? Math.round((v.points / v.max) * 100) : 0;
    return `<div class="bar-row"><div class="bar-top"><span><b>${esc(k[0].toUpperCase() + k.slice(1))}</b> <span class="muted">${esc(v.why)}</span></span><span class="mono"><b>${esc(v.points)}</b>/${esc(v.max)}</span></div>
      <div class="bar ${pct >= 60 ? "green" : pct >= 40 ? "amber" : "red"}"><i style="width:${pct}%"></i></div></div>`;
  }).join("");
  const emailField = UI.editEmail
    ? `<div class="actions"><input type="email" id="email-input" value="${esc(c.email)}" style="max-width:280px"><button class="btn primary small" data-act="save-email">Save</button><button class="btn small" data-act="cancel-email">Cancel</button></div>`
    : `<div class="value">${c.email ? esc(c.email) : `<span class="muted">No email yet</span>`} ${ROLE === "hr" ? `<button class="btn ghost small" data-act="edit-email">${icon("pencil", "sm")} ${c.email ? "Change" : "Add email"}</button>` : ""}</div>
       ${c.email_source ? `<div class="small muted">${esc(c.email_source)}</div>` : ""}`;
  const hasInterview = c.interview_label || (c.questions && c.questions.length) || c.result;
  setView(`<a class="back" href="#/candidates">${icon("arrow-left", "sm")} All candidates</a>
    <div class="card" style="display:flex;gap:20px;align-items:center;flex-wrap:wrap">
      <div class="avatar" style="width:64px;height:64px;font-size:22px;background:#E0EAFF;color:#1D4ED8">${esc(initials(c.name))}</div>
      <div style="flex:1;min-width:220px"><h2 style="margin:0 0 8px;font-size:24px">${esc(c.name)}</h2>
        <div class="chips"><span class="chip gray">${esc(c.app_no)}</span>${chip(c)}${c.area ? `<span class="chip purple">${esc(c.area)}</span>` : ""}${c.score != null ? scoreChip(c.score) : ""}${c.work_id ? `<span class="chip green">${icon("id-card", "sm")} Work ID ${esc(c.work_id)}</span>` : ""}</div></div>
      <a class="btn" href="/api/candidates/${encodeURIComponent(c.app_no)}/cv">${icon("download")} Download CV</a></div>
    <div style="margin-top:24px">${ROLE === "hr" ? nextStep(c, areas.areas) : banner("blue", "info", "You are viewing this as the Interviewer.", " Open it from the Interviews page to enter a result.")}</div>
    ${flags.length ? `<div class="card" style="margin-top:24px">${cardHead("triangle-alert", "amber", "Notes to check", `<span class="hint">From the AI team</span>`)}
      ${flags.map((f) => `<div class="note">${icon("triangle-alert")}<div class="grow"><div>${esc(f.text)}</div><div class="small muted">${esc(f.by)} - ${esc(fmtTime(f.at))}</div></div>
        ${ROLE === "hr" ? `<button class="btn small" data-act="resolve" data-i="${f.index}">${icon("check", "sm")} Mark as checked</button>` : ""}</div>`).join("")}</div>` : ""}
    <div class="grid two">
      <div class="card">${cardHead("user", "blue", "Profile", c.profile_source ? sourceTag(c.profile_source === "AI" ? "Read by AI, checked against the CV" : "Made by rules") : "")}
        <div class="field"><div class="label">Email</div>${emailField}</div>
        <div class="field"><div class="label">Phone</div><div class="value">${esc(p.phone || "-")}</div></div>
        <div class="field"><div class="label">Education</div>${list(p.education, "None found")}</div>
        <div class="field"><div class="label">Skills</div>${p.skills && p.skills.length ? `<div class="chips">${p.skills.map((s) => `<span class="chip gray">${esc(s)}</span>`).join("")}</div>` : `<span class="muted">None found</span>`}</div>
        <div class="field"><div class="label">Projects</div>${list(p.projects, "None found")}</div>
        <div class="field"><div class="label">Experience</div>${list(p.experience, "None (normal for a student)")}</div>
        <div class="actions" style="margin-top:18px"><button class="btn small" data-act="toggle-cv">${icon("eye", "sm")} ${UI.showCv ? "Hide" : "Show"} the CV text</button><span class="small muted">${esc(c.cv_filename)}</span></div>
        ${UI.showCv ? `<div class="cvtext" style="margin-top:12px">${esc(c.cv_text)}</div>` : ""}</div>
      <div class="card">${cardHead("layers", "purple", "Area and score", c.area_source ? sourceTag(c.area_source) : "")}
        ${c.area ? `<div class="field"><div class="label">Area</div><div class="value" style="font-size:20px;font-weight:700">${esc(c.area)}</div></div>` : `<div class="field"><div class="label">Area</div><div class="value muted">${c.suggested_new_area ? "AI suggested a new area: " + esc(c.suggested_new_area) : "Not chosen yet"}</div></div>`}
        ${c.area_reasons.length ? `<div class="field"><div class="label">Why</div>${list(c.area_reasons, "")}</div>` : ""}
        ${c.area_evidence.length ? `<div class="field"><div class="label">Evidence from the CV</div>${c.area_evidence.map((e) => `<div class="quote">"${esc(e)}"</div>`).join("")}</div>` : ""}
        ${c.score != null ? `<div class="field"><div class="label">Score (calculated by code)</div><div class="score-big"><b style="color:var(--${scoreColor(c.score)}-ink)">${esc(c.score)}</b><span class="muted">/ 100</span></div><div class="bars">${bars}</div>
          <div class="legend"><span><i style="background:#43B580"></i>60+ Shortlisted</span><span><i style="background:#E9A23B"></i>50-59 You decide</span><span><i style="background:#EF4444"></i>Below 50 Not shortlisted</span></div></div>` : ""}
        ${c.gaps.length ? `<div class="field"><div class="label">Skill gaps</div><div class="chips">${c.gaps.map((g) => `<span class="chip red">${esc(g)}</span>`).join("")}</div></div>` : ""}
        ${(c.area_matrix && c.area_matrix.length > 1) ? `<div class="field"><div class="label">Fit across all areas</div><div class="rows" style="gap:8px;margin-top:6px">${c.area_matrix.map((m) => `<div class="routine" style="align-items:center;padding:8px 12px"><div class="grow"><b>${esc(m.area)}</b> ${m.area === c.area ? `<span class="chip purple" style="padding:2px 8px;font-size:11px">Current</span>` : ""}<div class="small muted">${esc(m.matched_required.length)}/${esc(m.total_required)} required skills${m.matched_preferred.length ? ` + ${esc(m.matched_preferred.length)} preferred` : ""}</div></div><span class="chip ${scoreColor(m.score)}">${esc(m.score)}/100</span>${ROLE === "hr" && m.area !== c.area && ["needs_area", "borderline", "not_shortlisted_check"].includes(c.status) ? `<button class="btn small" data-act="quick-area" data-area="${esc(m.area)}">Use</button>` : ""}</div>`).join("")}</div></div>` : ""}</div>
    </div>
    ${askCvCard(c)}
    ${hasInterview ? `<div class="card" style="margin-top:24px">${cardHead("calendar-check", "green", "Interview", c.questions_source ? sourceTag(c.questions_source === "AI" ? "Questions by AI" : c.questions_source) : "")}
      <div class="grid two" style="gap:20px"><div><div class="field"><div class="label">Date and time</div><div class="value">${esc(c.interview_label || "-")} ${ROLE === "hr" && ["invite_ready", "awaiting_result"].includes(c.status) ? `<button class="btn ghost small" data-act="change-slot" data-cur="${esc(c.interview_at || "")}">${icon("pencil", "sm")} Change slot</button>` : ""}</div></div>
        <div class="field"><div class="label">Result</div><div class="value">${c.result ? `<span class="chip ${c.result === "Pass" ? "green" : c.result === "Fail" ? "red" : "amber"}">${esc(c.result)}</span> <span class="small muted">${esc(fmtTime(c.result_at))} - decided by the interviewer</span>` : `<span class="muted">Not entered yet</span>`}</div></div>
        ${c.result_comment ? `<div class="field"><div class="label">Interviewer's comment</div><div class="value">${esc(c.result_comment)}</div></div>` : ""}</div>
        <div><div class="label">Questions for the interviewer</div>${c.questions.length ? `<ol class="clean">${c.questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ol>` : `<span class="muted">-</span>`}</div></div></div>` : ""}
    ${c.drafts.length ? `<div class="card" id="emails" style="margin-top:24px">${cardHead("mail", "amber", "Emails", `<span class="hint">Nothing is sent without your release</span>`)}<div class="rows">${c.drafts.slice().reverse().map((d) => mailBlock(d)).join("")}</div></div>` : ""}
    ${c.work_id ? `<div class="card" style="margin-top:24px">${cardHead("id-card", "green", "Onboarding", c.checklist.length ? `<span class="chip ${c.checklist.every((i) => i.done) ? "green" : "gray"}">${c.checklist.filter((i) => i.done).length} of ${c.checklist.length} done</span>` : "")}
      <div class="grid two" style="gap:20px"><div><div class="label">Work ID</div><div style="font-size:44px;font-weight:700;letter-spacing:.04em">${esc(c.work_id)}</div><div class="small muted">Issued by plain code after the Pass. Never reused.</div></div>
      <div><div class="label">Induction checklist</div>${c.checklist.length ? `<div class="rows">${c.checklist.map((i, idx) => `<div class="routine ${ROLE === "hr" ? "click" : ""}" ${ROLE === "hr" ? `data-act="toggle-check" data-i="${idx}"` : ""} style="align-items:center;cursor:${ROLE === "hr" ? "pointer" : "default"}"><span style="color:var(${i.done ? "--green-ink" : "--faint"})">${icon(i.done ? "circle-check" : "clock", "sm")}</span><span class="grow" style="${i.done ? "text-decoration:line-through;color:var(--muted)" : ""}">${esc(i.item)}</span>${ROLE === "hr" ? `<span class="small muted">${i.done ? "Done" : "Mark done"}</span>` : ""}</div>`).join("")}</div>` : `<span class="muted">Being prepared</span>`}</div></div></div>` : ""}
    <div class="card" style="margin-top:24px">${cardHead("activity", "purple", "Timeline", `<button class="btn small" data-act="toggle-runs">${UI.showRuns ? "Hide" : "Show"} AI steps</button>`)}
      <div class="timeline">${c.events.slice().reverse().map((e) => `<div class="tl"><time>${esc(fmtTime(e.at))}</time><div>${actorTag(e.actor)} <span style="margin-left:6px">${esc(e.text)}</span></div></div>`).join("")}</div>
      ${UI.showRuns ? `<table class="list" style="margin-top:14px"><thead><tr><th>Time</th><th>Employee</th><th>Routine</th><th>Outcome</th><th>Model calls</th><th>Seconds</th></tr></thead><tbody>
        ${c.runs.map((r) => `<tr><td>${esc(fmtTime(r.at))}</td><td>${esc(r.employee)}</td><td>${esc(r.routine)}</td><td>${outcomeChip(r.outcome)}${r.note ? `<div class="small muted">${esc(r.note)}</div>` : ""}</td><td>${esc(r.model_calls)}</td><td>${esc(r.seconds)}</td></tr>`).join("")}</tbody></table>` : ""}</div>`);
  view.dataset.app = c.app_no;
}
function outcomeChip(o) {
  const m = { ok: ["green", "Passed checks"], fixed: ["blue", "Fixed after a check"], fallback: ["amber", "Fell back to rules"], stopped: ["red", "Stopped: model not running"], error: ["red", "Error"] }[o] || ["gray", o];
  return `<span class="chip ${m[0]}">${esc(m[1])}</span>`;
}

async function pReview() {
  title("Review queue");
  const r = await api("/api/review");
  const total = r.decisions.length + r.notes.length;
  setView(`${total ? banner("amber", "clipboard-check", `${total} item(s) need you.`, " Decisions first, then quick checks.") : banner("green", "circle-check", "The review queue is empty.", " Nothing needs a decision right now.")}
    <div class="card">${cardHead("mail", "blue", "Emails waiting for release")}
      <div class="row"><div class="grow"><div class="title">${esc(r.replies_waiting)} email(s) waiting for your release</div><div class="sub">Invitations, replies and acceptance emails drafted by the AI team. Nothing reaches a student until you release it.</div></div><a class="btn" href="#/replies">Open Replies ${icon("arrow-right", "sm")}</a></div></div>
    <div class="grid two"><div class="stack">
      <div class="card">${cardHead("clipboard-check", "amber", "Decisions for you", `<span class="hint">${r.decisions.length}</span>`)}
        <div class="rows">${r.decisions.length ? r.decisions.map((c) => `<a class="row" href="#/candidate/${encodeURIComponent(c.app_no)}">${dateBox(c.updated_at)}
          <div class="grow"><div class="title">${esc(c.name)} <span class="small muted">${esc(c.app_no)}</span></div><div class="sub">${esc(c.reason)}</div></div>${chip(c)}${icon("arrow-right", "sm")}</a>`).join("") : empty("No decisions waiting.", "circle-check")}</div></div>
    </div><div class="stack">
      <div class="card">${cardHead("triangle-alert", "amber", "Notes to check", `<span class="hint">${r.notes.length}</span>`)}
        ${r.notes.length ? r.notes.map((n) => `<div class="note">${icon("triangle-alert")}<div class="grow"><div><b>${esc(n.name)}</b> <a href="#/candidate/${encodeURIComponent(n.app_no)}">${esc(n.app_no)}</a></div><div>${esc(n.text)}</div><div class="small muted">${esc(n.by)} - ${esc(fmtTime(n.at))}</div></div>
          <button class="btn small" data-act="resolve" data-app="${esc(n.app_no)}" data-i="${n.index}">${icon("check", "sm")} Checked</button></div>`).join("") : empty("No notes to check.", "circle-check")}</div>
      ${r.suggested_areas.length ? `<div class="card">${cardHead("layers", "purple", "New areas suggested by the AI")}<div class="rows">${r.suggested_areas.map((s) => `<div class="row"><div class="grow"><div class="title">${esc(s.name)}</div><div class="sub">For ${esc(s.app_nos.join(", "))}</div></div><a class="btn small" href="#/areas/new:${encodeURIComponent(s.name)}">${icon("plus", "sm")} Add this area</a></div>`).join("")}</div></div>` : ""}
    </div></div>`);
}

async function pReplies(arg) {
  title("Replies");
  if (arg === "released" || arg === "waiting") UI.repliesTab = arg;
  const drafts = await api(`/api/drafts?state=${UI.repliesTab}`);
  const readyCount = UI.repliesTab === "waiting" ? drafts.filter((d) => d.can_release).length : 0;
  const releaseAllBtn = readyCount > 1 && ROLE === "hr"
    ? `<button class="btn primary small" data-act="release-all" data-n="${readyCount}">${icon("send", "sm")} Release all ready (${readyCount})</button>`
    : "";
  setView(`<div class="card">${cardHead("mail", "amber", "Emails drafted by the AI team", `<div class="actions">${releaseAllBtn}<div class="seg"><button class="${UI.repliesTab === "waiting" ? "on" : ""}" data-act="tab" data-t="waiting">Waiting for release</button><button class="${UI.repliesTab === "released" ? "on" : ""}" data-act="tab" data-t="released">Released</button></div></div>`)}
    <p class="muted small" style="margin-top:-6px">Read each email, edit it if needed, then release it. In this prototype a released email is saved in the data/outbox folder. Nothing is sent.</p>
    <div class="rows">${drafts.length ? drafts.map((d) => mailBlock(d, { showCandidate: true })).join("") : empty(UI.repliesTab === "waiting" ? "No emails are waiting for release." : "No emails released yet.", "mail")}</div></div>`);
}

async function pAreas(arg) {
  title("Areas");
  const a = UI.areas = await api("/api/areas");
  setView(`${a.suggested.length ? banner("blue", "sparkles", "The AI suggested new areas.", " Add one only if SLT really offers it. " + a.suggested.map((s) => `${s.name} (${s.count})`).join(", ") + ".",
      `<div class="actions">${a.suggested.map((s) => `<button class="btn small" data-act="area-new" data-name="${esc(s.name)}">${icon("plus", "sm")} Add ${esc(s.name)}</button>`).join("")}</div>`) : ""}
    <div class="card" ${a.suggested.length ? 'style="margin-top:24px"' : ""}>${cardHead("layers", "purple", "Internship areas", `<button class="btn primary" data-act="area-new">${icon("plus")} Add area</button>`)}
      <p class="muted small" style="margin-top:-6px">The Recruiter chooses from these areas. CVs are scored against the required skills (skills ${esc(40)}, projects ${esc(30)}, education ${esc(20)}, experience ${esc(10)}).</p>
      <div class="grid two" style="gap:18px">${a.areas.map((x) => `<div class="card" style="box-shadow:none;border:1px solid var(--line)">
        <div class="card-head" style="margin-bottom:10px"><h2>${esc(x.name)}</h2>${x.active ? `<span class="chip green">Active</span>` : `<span class="chip gray">Turned off</span>`}<div class="spacer"></div><span class="small muted">${esc(x.candidates)} candidate(s)</span></div>
        <p class="muted" style="margin-top:0">${esc(x.description || "No description.")}</p>
        <div class="field"><div class="label">Required skills</div><div class="chips">${x.required_skills.map((s) => `<span class="chip blue">${esc(s)}</span>`).join("") || `<span class="muted">None</span>`}</div></div>
        <div class="field"><div class="label">Preferred skills</div><div class="chips">${x.preferred_skills.map((s) => `<span class="chip gray">${esc(s)}</span>`).join("") || `<span class="muted">None</span>`}</div></div>
        <div class="actions" style="margin-top:16px"><button class="btn small" data-act="area-edit" data-id="${x.id}">${icon("pencil", "sm")} Edit</button>
          <button class="btn small" data-act="area-toggle" data-id="${x.id}">${x.active ? "Turn off" : "Turn on"}</button><span class="small muted">Added by ${esc(x.added_by)}</span></div></div>`).join("")}</div></div>`);
  if (arg && arg.startsWith("new:")) { history.replaceState(null, "", "#/areas"); areaForm(null, arg.slice(4)); }
}
function areaForm(area, name = "") {
  const v = area || { name, description: "", required_skills: [], preferred_skills: [], keywords: [], checklist: [] };
  openDialog(`<h3>${area ? "Edit area" : "Add area"}</h3><p class="muted small">Separate skills with commas. Only add an area that SLT really offers.</p>
    <div class="form-row"><label for="af-name">Name</label><input type="text" id="af-name" value="${esc(v.name)}" maxlength="40"></div>
    <div class="form-row"><label for="af-desc">Description</label><textarea id="af-desc" rows="2" style="min-height:60px">${esc(v.description)}</textarea></div>
    <div class="form-row"><label for="af-req">Required skills</label><input type="text" id="af-req" value="${esc(v.required_skills.join(", "))}" placeholder="For example: Recruitment, Interviewing, Excel"><div class="help">Used for the score. At least one.</div></div>
    <div class="form-row"><label for="af-pref">Preferred skills</label><input type="text" id="af-pref" value="${esc(v.preferred_skills.join(", "))}"></div>
    <div class="form-row"><label for="af-kw">Keywords for related projects</label><input type="text" id="af-kw" value="${esc(v.keywords.join(", "))}"></div>
    <div class="form-row"><label for="af-check">Extra induction checklist items (one per line)</label><textarea id="af-check" rows="3" style="min-height:70px">${esc(v.checklist.join("\n"))}</textarea></div>
    <div class="actions"><button class="btn" data-dlg="cancel">Cancel</button><button class="btn primary" data-dlg="save">${icon("check")} Save area</button></div>`);
  const d = $("#dialog");
  d.querySelector('[data-dlg="cancel"]').onclick = closeDialog;
  d.querySelector('[data-dlg="save"]').onclick = async () => {
    const body = { name: $("#af-name").value, description: $("#af-desc").value, required_skills: $("#af-req").value,
      preferred_skills: $("#af-pref").value, keywords: $("#af-kw").value, checklist: $("#af-check").value, active: area ? area.active : true };
    try {
      if (area) await api(`/api/areas/${area.id}`, { method: "PUT", body });
      else await api("/api/areas", { method: "POST", body });
      closeDialog(); toast(`Saved the area ${body.name}.`); UI.areas = null; lastHTML = ""; render();
    } catch (e) { toast(e.message, true); }
  };
}

async function pTeam() {
  title("AI team");
  const t = await api("/api/team");
  const down = !t.model.ok || (t.notice && t.notice.text);
  const bm = t.benchmark || {};
  const benchCard = `<div class="card" style="margin-top:24px">${cardHead("shield-check", "green", "Guardrail & Model Reliability Benchmark", `<span class="hint">${esc(t.model.model || "Local LLM")}</span>`)}
    <div class="num-grid">
      <div class="num-box total"><b>${esc(bm.verified_pct ?? 100)}%</b><span>Verified output rate</span></div>
      <div class="num-box"><b>${esc(bm.first_pass_pct ?? 100)}%</b><span>First-pass check rate</span></div>
      <div class="num-box"><b>${esc(bm.self_healed ?? 0)}</b><span>Self-healed after check</span></div>
      <div class="num-box"><b>${esc(bm.fallback ?? 0)}</b><span>Rule fallbacks used</span></div>
      <div class="num-box"><b>${esc(bm.avg_seconds ?? 0)}s</b><span>Avg latency (${esc(bm.total_model_steps ?? 0)} steps)</span></div>
    </div></div>`;
  setView(`<div class="banner ${down ? "red" : t.paused ? "amber" : "blue"}"><div class="hicon ${down ? "red" : "purple"}">${icon("bot")}</div>
      <div class="grow"><b>${down ? "The model server is not running, so the AI team is waiting." : t.paused ? "The AI team is paused." : "Four AI employees work on their own schedule."}</b>
      <span class="muted small"> Each one is a folder of Markdown files (ROLE, SCHEDULE, RELEASES and one SKILL file per routine). The status of a candidate hands the work from one to the next.</span></div>
      ${ROLE === "hr" ? `<div class="actions"><button class="btn primary" data-act="run" data-who="all">${icon("play")} Run all now</button><button class="btn" data-act="pause" data-p="${t.paused ? "0" : "1"}">${icon(t.paused ? "play" : "pause")} ${t.paused ? "Resume" : "Pause"}</button></div>` : ""}</div>
    ${benchCard}
    <div class="grid two">${t.employees.map((e, i) => `<div class="card">
      <div class="emp"><div class="emp-icon e${i}">${icon(["user-round-search", "calendar-check", "id-card", "activity"][i], "lg")}</div>
        <div><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><h2 style="margin:0;font-size:19px">${esc(e.name)}</h2>
          ${t.paused ? `<span class="chip gray">Paused</span>` : e.state === "working" ? `<span class="chip blue"><i class="dot busy"></i>${esc(e.doing)}</span>` : `<span class="chip green">Ready</span>`}</div>
          <div class="small muted">${esc((e.schedule.text || "").split("\n")[0])}${e.next_run ? " - next run " + esc(fmtTime(e.next_run)) : ""}</div></div></div>
      <p style="margin:14px 0">${esc(e.summary)}</p>
      <div class="chips"><span class="chip green">${esc(e.day.ok)} passed checks</span><span class="chip blue">${esc(e.day.fixed)} fixed</span><span class="chip amber">${esc(e.day.fallback)} fell back</span>${e.day.error || e.day.stopped ? `<span class="chip red">${esc(e.day.error + e.day.stopped)} stopped</span>` : ""}<span class="small muted" style="align-self:center">last 24 hours</span></div>
      <div class="label" style="margin-top:18px">Routines</div>
      ${e.routines.map((r) => `<div class="routine">${icon(r.uses_model ? "sparkles" : "list-checks", "sm")}<div class="grow"><b>${esc(r.name)}</b> <span class="who-tag ${r.uses_model ? "ai" : "rules"}">${r.uses_model ? "Model + checks" : "Plain code"}</span><div class="small muted">${esc(r.starts_when ? "Starts when " + r.starts_when : "")}</div></div></div>`).join("")}
      ${e.lessons.length ? `<div class="label" style="margin-top:18px">What it has learned</div><ul class="clean small">${e.lessons.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : ""}
      <div class="label" style="margin-top:18px">Recent steps</div>
      ${e.runs.length ? `<div class="rows">${e.runs.slice(0, 5).map((r) => `<div class="row" style="padding:10px 12px"><div class="grow"><div class="title small">${esc(r.routine)}</div><div class="sub">${esc(fmtTime(r.at))} - ${esc(r.seconds)} s - ${esc(r.model_calls)} model call(s)</div></div>${outcomeChip(r.outcome)}</div>`).join("")}</div>` : `<span class="muted small">No runs yet.</span>`}
      ${ROLE === "hr" ? `<div class="actions" style="margin-top:16px"><button class="btn small" data-act="run" data-who="${esc(e.key)}">${icon("play", "sm")} Run ${esc(e.name)} now</button></div>` : ""}
    </div>`).join("")}</div>`);
}

// ================================================================ Interviewer pages
async function pInterviews() {
  title("Interviews");
  const r = await api("/api/interviews");
  const row = (c, click = true) => `<${click ? `a href="#/interview/${encodeURIComponent(c.app_no)}"` : "div"} class="row">${dateBox(c.interview_at || c.updated_at)}
    <div class="grow"><div class="title">${esc(c.name)} <span class="small muted">${esc(c.app_no)}</span></div><div class="sub">${icon("clock", "sm")} ${esc(c.interview_label || "-")} - ${esc(c.area)}${c.score != null ? " - score " + esc(c.score) : ""}</div></div>
    ${c.result ? `<span class="chip ${c.result === "Pass" ? "green" : c.result === "Fail" ? "red" : "amber"}">${esc(c.result)}</span>` : click ? "" : `<span class="chip gray">Not released</span>`}${click ? icon("arrow-right", "sm") : ""}</${click ? "a" : "div"}>`;
  const LIMIT = 4;
  const list = (items, key, click, none, ic) => {
    if (!items.length) return empty(none, ic);
    const all = UI.showAll === key;
    const rows = (all ? items : items.slice(0, LIMIT)).map((c) => row(c, click)).join("");
    const btn = items.length > LIMIT ? `<button class="btn ghost small" data-act="show-all" data-k="${all ? "" : key}" style="margin-top:8px">${all ? "Show fewer" : "Show all " + items.length}</button>` : "";
    return `<div class="rows">${rows}</div>${btn}`;
  };
  setView(`${hero({ kicker: "Welcome back", name: "Interviewer", initialsText: "IN",
      chips: [`<span class="chip on">${icon("calendar-check", "sm")} ${r.waiting.length} waiting for your result</span>`, `<span class="chip">${icon("hourglass", "sm")} ${r.on_hold.length} on hold</span>`,
        `<span class="chip">${icon("shield-check", "sm")} Your result is final; the AI cannot change it</span>`] })}
    <div style="margin-top:24px">${r.waiting.length ? banner("amber", "calendar-check", `${r.waiting.length} interview(s) are waiting for your result.`, " Open one, do the interview and enter Pass, Fail or Hold.") : banner("green", "circle-check", "No results are waiting for you.", "")}</div>
    <div class="grid two even">
      <div class="card">${cardHead("calendar-check", "blue", "Waiting for your result", `<span class="hint">${r.waiting.length}</span>`)}${list(r.waiting, "waiting", true, "Nothing waiting.", "calendar-check")}</div>
      <div class="card">${cardHead("mail", "gray", "Coming up", `<span class="hint">${r.invitation_not_released.length}, invitation not released yet</span>`)}${list(r.invitation_not_released, "coming", false, "None.", "mail")}</div>
      <div class="card">${cardHead("hourglass", "amber", "On hold", `<span class="hint">${r.on_hold.length}</span>`)}${list(r.on_hold, "hold", true, "No one is on hold.", "hourglass")}</div>
      <div class="card">${cardHead("list-checks", "green", "Your recent results")}${list(r.done, "done", false, "No results yet.", "list-checks")}</div>
    </div>`);
}

async function pInterview(appNo) {
  title("Interview");
  const c = await api(`/api/candidates/${encodeURIComponent(appNo)}`);
  const p = c.profile || {};
  const open = c.status === "awaiting_result" || c.status === "on_hold";
  const form = open ? `<div class="result-pick">
      <label class="pass"><input type="radio" name="result" value="Pass">${icon("circle-check", "lg")}<span>Pass<div class="small muted" style="font-weight:400">Offer an internship</div></span></label>
      <label class="fail"><input type="radio" name="result" value="Fail">${icon("circle-x", "lg")}<span>Fail<div class="small muted" style="font-weight:400">No offer</div></span></label>
      ${c.status === "awaiting_result" ? `<label class="hold"><input type="radio" name="result" value="Hold">${icon("hourglass", "lg")}<span>Hold<div class="small muted" style="font-weight:400">Decide later</div></span></label>` : ""}</div>
    <div class="form-row" style="margin-top:18px"><label for="result-comment">Comment (optional)</label><textarea id="result-comment" rows="4" placeholder="Short notes for the HR officer. Not sent to the student."></textarea></div>
    <div class="actions" style="margin-top:18px"><button class="btn primary" data-act="save-result">${icon("check")} Save result</button><span class="small muted">The AI team takes over after you save.</span></div>`
    : c.result ? `<div class="value"><span class="chip ${c.result === "Pass" ? "green" : c.result === "Fail" ? "red" : "amber"}" style="font-size:15px;padding:7px 14px">${esc(c.result)}</span></div>
      <p class="muted">Saved ${esc(fmtTime(c.result_at))}. ${c.result_comment ? "Comment: " + esc(c.result_comment) : ""}</p><p class="small muted">Now: ${esc(c.status_label)}.</p>`
    : `<p class="muted">The result can be entered after the HR officer releases the invitation.</p>`;
  setView(`<a class="back" href="#/interviews">${icon("arrow-left", "sm")} All interviews</a>
    <div class="card" style="display:flex;gap:20px;align-items:center;flex-wrap:wrap">
      <div class="avatar" style="width:64px;height:64px;font-size:22px;background:#E2FBE8;color:#15803D">${esc(initials(c.name))}</div>
      <div style="flex:1"><h2 style="margin:0 0 8px;font-size:24px">${esc(c.name)}</h2><div class="chips"><span class="chip gray">${esc(c.app_no)}</span>${chip(c)}<span class="chip purple">${esc(c.area)}</span>${scoreChip(c.score)}</div></div>
      <div class="small muted">${icon("clock", "sm")} ${esc(c.interview_label || "")}</div></div>
    <div class="grid side"><div class="stack">
      <div class="card">${cardHead("list-checks", "blue", "Questions to ask", c.questions_source ? sourceTag(c.questions_source === "AI" ? "Prepared by AI" : c.questions_source) : "")}
        ${c.questions.length ? `<ol class="clean" style="line-height:1.7">${c.questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ol>` : `<span class="muted">No questions prepared.</span>`}</div>
      <div class="card">${cardHead("user", "purple", "About the student")}
        <div class="field"><div class="label">Education</div>${(p.education || []).map((x) => `<div>${esc(x)}</div>`).join("") || "-"}</div>
        <div class="field"><div class="label">Skills</div><div class="chips">${(p.skills || []).map((s) => `<span class="chip gray">${esc(s)}</span>`).join("") || "-"}</div></div>
        <div class="field"><div class="label">Projects</div><ul class="clean">${(p.projects || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>-</li>"}</ul></div>
        ${c.gaps.length ? `<div class="field"><div class="label">Skill gaps for ${esc(c.area)}</div><div class="chips">${c.gaps.map((g) => `<span class="chip red">${esc(g)}</span>`).join("")}</div></div>` : ""}
        <div class="actions" style="margin-top:14px"><button class="btn small" data-act="toggle-cv">${icon("eye", "sm")} ${UI.showCv ? "Hide" : "Show"} the CV text</button><a class="btn small" href="/api/candidates/${encodeURIComponent(c.app_no)}/cv">${icon("download", "sm")} Download CV</a></div>
        ${UI.showCv ? `<div class="cvtext" style="margin-top:12px">${esc(c.cv_text)}</div>` : ""}</div>
      ${askCvCard(c)}
    </div><div class="stack">
      <div class="card">${cardHead("award", "green", "Your result")}${form}</div>
    </div></div>`);
}

// ================================================================ actions (one click handler for every button)
async function act(fn, okMsg) {
  try { const r = await fn(); if (okMsg) toast(typeof okMsg === "function" ? okMsg(r) : okMsg); lastHTML = ""; await refreshState(); await render(); }
  catch (e) { toast(e.message, true); }
}
const ACTS = {
  "brief": () => act(() => api("/api/brief", { method: "POST" }), "The Chief of staff is writing the brief. It appears here in a moment."),
  "remove-file": (b) => { UI.files.splice(+b.dataset.i, 1); lastHTML = ""; pAdd(); },
  "clear-files": () => { UI.files = []; UI.uploadResults = null; lastHTML = ""; pAdd(); },
  "upload": async (b) => {
    const form = new FormData();
    UI.files.forEach((f) => form.append("files", f, f.name));
    const email = $("#cv-email");
    if (email && !email.disabled && email.value.trim()) form.append("email", email.value.trim());
    b.disabled = true;
    try {
      const r = await api("/api/cvs", { method: "POST", form });
      UI.uploadResults = r.results; UI.files = [];
      const ok = r.results.filter((x) => x.ok).length;
      toast(ok ? `${ok} CV(s) added. The Recruiter will read them now.` : "No CV was added.", !ok);
    } catch (e) { toast(e.message, true); }
    lastHTML = ""; refreshState(); pAdd();
  },
  "samples": () => act(async () => { const r = await api("/api/samples", { method: "POST" }); UI.uploadResults = r.results; return r; },
    (r) => `${r.results.filter((x) => x.ok).length} sample CV(s) added.`),
  "filter": (b) => { UI.candFilter = b.dataset.f; history.replaceState(null, "", "#/candidates"); lastHTML = ""; pCandidates(); },
  "show-all": (b) => { UI.showAll = b.dataset.k; lastHTML = ""; render(); },
  "tab": (b) => { UI.repliesTab = b.dataset.t; lastHTML = ""; pReplies(); },
  "toggle-cv": () => { UI.showCv = !UI.showCv; lastHTML = ""; render(); },
  "toggle-runs": () => { UI.showRuns = !UI.showRuns; lastHTML = ""; render(); },
  "edit-email": () => { UI.editEmail = true; lastHTML = ""; render().then(() => $("#email-input")?.focus()); },
  "cancel-email": () => { UI.editEmail = false; lastHTML = ""; render(); },
  "save-email": () => act(async () => { await api(`/api/candidates/${encodeURIComponent(current.arg)}/email`, { method: "POST", body: { email: $("#email-input").value } }); UI.editEmail = false; }, "Email saved."),
  "set-area": () => act(() => api(`/api/candidates/${encodeURIComponent(current.arg)}/area`, { method: "POST", body: { area: $("#area-pick").value } }),
    (r) => `Area saved. Score ${r.score}/100.`),
  "quick-area": (b) => act(() => api(`/api/candidates/${encodeURIComponent(current.arg)}/area`, { method: "POST", body: { area: b.dataset.area } }),
    (r) => `Switched area to ${b.dataset.area}. Score ${r.score}/100.`),
  "ask-preset": (b) => {
    const inp = $("#ask-cv-q");
    if (inp) inp.value = b.dataset.q || "";
    ACTS["ask-cv"]();
  },
  "ask-cv": async () => {
    const inp = $("#ask-cv-q");
    const question = inp ? inp.value.trim() : "";
    if (!question) { toast("Write a question about this CV first.", true); return; }
    UI.cvLoading = true;
    lastHTML = "";
    await render();
    try {
      UI.cvAnswer = await api(`/api/candidates/${encodeURIComponent(current.arg)}/ask`, { method: "POST", body: { question } });
    } catch (e) {
      toast(e.message, true);
    } finally {
      UI.cvLoading = false;
      lastHTML = "";
      await render();
    }
  },
  "decide": async (b) => {
    const d = b.dataset.d;
    const text = { shortlist: ["Shortlist this student?", "The Coordinator will book an interview and draft the invitation for you to release.", "Shortlist"],
      not_shortlist: ["Mark as Not shortlisted?", "The Coordinator will draft a polite reply for you to release.", "Not shortlisted"],
      confirm: ["Confirm Not shortlisted?", "The Coordinator will draft a polite reply for you to release.", "Confirm"] }[d];
    if (!(await confirmBox({ heading: text[0], text: text[1], ok: text[2] }))) return;
    act(() => api(`/api/candidates/${encodeURIComponent(current.arg)}/decision`, { method: "POST", body: { decision: d } }), "Saved. The AI team takes it from here.");
  },
  "retry": () => act(() => api(`/api/candidates/${encodeURIComponent(current.arg)}/retry`, { method: "POST" }), "Sent back to the Recruiter."),
  "close": async () => {
    if (!(await confirmBox({ heading: "Close this application?", text: "No reply will be drafted. You can still see it under Closed.", ok: "Close application", danger: true }))) return;
    act(() => api(`/api/candidates/${encodeURIComponent(current.arg)}/close`, { method: "POST" }), "Application closed.");
  },
  "resolve": (b) => act(() => api(`/api/candidates/${encodeURIComponent(b.dataset.app || current.arg)}/flags/${b.dataset.i}/resolve`, { method: "POST" }), "Marked as checked."),
  "toggle-check": (b) => act(() => api(`/api/candidates/${encodeURIComponent(current.arg)}/checklist/${b.dataset.i}/toggle`, { method: "POST" })),
  "change-slot": async () => {
    try {
      const r = await api("/api/slots");
      const slots = r.slots || [];
      if (!slots.length) { toast("No free interview slots available.", true); return; }
      openDialog(`<h3>Change interview slot</h3><p class="muted small">Pick a free 45-minute slot on a working day. If the invitation email has not been released yet, its date and time will be updated automatically.</p>
        <div class="form-row"><label for="slot-pick">Available slots</label>
          <select id="slot-pick">${slots.map((s) => `<option value="${esc(s.iso)}">${esc(s.label)}</option>`).join("")}</select></div>
        <div class="actions"><button class="btn" data-dlg="cancel">Cancel</button><button class="btn primary" data-dlg="save">${icon("check")} Save slot</button></div>`);
      const d = $("#dialog");
      d.querySelector('[data-dlg="cancel"]').onclick = closeDialog;
      d.querySelector('[data-dlg="save"]').onclick = async () => {
        const slot_iso = $("#slot-pick").value;
        closeDialog();
        await act(() => api(`/api/candidates/${encodeURIComponent(current.arg)}/slot`, { method: "POST", body: { slot_iso } }),
          (res) => `Interview moved to ${res.interview_label}.`);
      };
    } catch (e) { toast(e.message, true); }
  },
  "edit-draft": (b) => { UI.editDraft = +b.dataset.id; lastHTML = ""; render(); },
  "cancel-edit": () => { UI.editDraft = null; lastHTML = ""; render(); },
  "save-draft": async (b) => {
    try {
      const r = await api(`/api/drafts/${b.dataset.id}`, { method: "POST", body: { subject: $("#ed-subject").value, body: $("#ed-body").value } });
      UI.editDraft = null;
      toast(r.check_notes.length ? "Saved, but please read the warnings above the email." : "Saved.", r.check_notes.length > 0);
    } catch (e) { toast(e.message, true); }
    lastHTML = ""; render();
  },
  "release": async (b) => {
    if (!(await confirmBox({ heading: `Release the ${b.dataset.kind}?`, text: `To ${b.dataset.name}. In this prototype the email is saved to the outbox folder, not sent.`, ok: "Release" }))) return;
    act(() => api(`/api/drafts/${b.dataset.id}/release`, { method: "POST" }), "Released.");
  },
  "release-all": async (b) => {
    const n = b.dataset.n || "all";
    if (!(await confirmBox({ heading: `Release ${n} ready email(s)?`, text: "Each ready email will be saved to the outbox folder (not sent) and its candidate will move to the next step.", ok: "Release all" }))) return;
    act(() => api("/api/drafts/release-all", { method: "POST" }), (r) => `Released ${r.released} email(s).`);
  },
  "jump": (b, e) => { e.preventDefault(); $("#emails")?.scrollIntoView({ behavior: "smooth" }); },
  "area-new": (b) => areaForm(null, b.dataset.name || ""),
  "area-edit": (b) => areaForm(UI.areas.areas.find((x) => x.id === +b.dataset.id)),
  "area-toggle": async (b) => {
    const a = UI.areas.areas.find((x) => x.id === +b.dataset.id);
    act(() => api(`/api/areas/${a.id}`, { method: "PUT", body: { ...a, required_skills: a.required_skills, active: !a.active } }), a.active ? `${a.name} turned off.` : `${a.name} turned on.`);
  },
  "run": (b) => act(() => api("/api/run", { method: "POST", body: { employee: b.dataset.who } }), "Started. Watch the status update."),
  "pause": (b) => act(() => api("/api/pause", { method: "POST", body: { paused: b.dataset.p === "1" } }), b.dataset.p === "1" ? "The AI team is paused." : "The AI team is working again."),
  "save-result": async () => {
    const picked = document.querySelector('input[name="result"]:checked');
    if (!picked) { toast("Choose Pass, Fail or Hold first.", true); return; }
    const comment = $("#result-comment").value;
    const words = { Pass: "The Onboarding employee will issue a work ID and draft the acceptance email.", Fail: "The Coordinator will draft a polite reply.", Hold: "The Coordinator will draft a short hold note." }[picked.value];
    if (!(await confirmBox({ heading: `Save the result: ${picked.value}?`, text: `${words} The AI team cannot change your result.`, ok: `Save ${picked.value}` }))) return;
    act(() => api(`/api/candidates/${encodeURIComponent(current.arg)}/result`, { method: "POST", body: { result: picked.value, comment } }), "Result saved.");
  },
};
view.addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]");
  if (b && !b.disabled) { ACTS[b.dataset.act]?.(b, e); return; }
  const row = e.target.closest("[data-href]");
  if (row) location.hash = row.dataset.href;
});
view.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.id === "ask-cv-q" && !UI.cvLoading) {
    e.preventDefault();
    ACTS["ask-cv"]();
  }
});

// ================================================================ router
const ROUTES = {
  hr: { dashboard: pDashboard, add: pAdd, candidates: pCandidates, candidate: pCandidate, review: pReview, replies: pReplies, areas: pAreas, team: pTeam },
  interviewer: { interviews: pInterviews, interview: pInterview, team: pTeam, candidate: pCandidate },
};
const AUTO = new Set(["dashboard", "candidates", "candidate", "review", "replies", "team", "interviews", "interview"]);
function parseHash() {
  const h = location.hash.replace(/^#\/?/, "");
  const i = h.indexOf("/");
  return i < 0 ? { page: h, arg: "" } : { page: h.slice(0, i), arg: decodeURIComponent(h.slice(i + 1)) };
}
let rendering = false;
async function render() {
  const { page, arg } = parseHash();
  const fn = ROUTES[ROLE][page];
  if (!fn) { location.replace(HOME[ROLE]); return; }
  if (page !== current.page || arg !== current.arg) { UI.showCv = false; UI.showRuns = false; UI.editDraft = null; UI.editEmail = false; UI.cvAnswer = null; UI.cvLoading = false; lastHTML = ""; window.scrollTo(0, 0); }
  current = { page, arg };
  renderFrame();
  rendering = true;
  try { await fn(arg); }
  catch (e) { setView(`<div class="card">${empty(e.message, "triangle-alert")}<div class="actions" style="justify-content:center"><a class="btn" href="${HOME[ROLE]}">Back to start</a></div></div>`); }
  finally { rendering = false; }
}
window.addEventListener("hashchange", render);

async function tick() {
  await refreshState();
  if (!rendering && AUTO.has(current.page) && !busy()) {
    try { await ROUTES[ROLE][current.page]?.(current.arg); } catch { /* keep the page as it is */ }
  }
}
(async function start() {
  await refreshState();
  await render();
  setInterval(tick, 5000);
})();
