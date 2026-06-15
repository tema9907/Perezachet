const $ = (id) => document.getElementById(id);
const toast = (msg, kind = "") => {
  const t = $("toast");
  t.textContent = msg;
  t.className = `toast ${kind}`;
  setTimeout(() => t.classList.add("hidden"), 4000);
  t.classList.remove("hidden");
};

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function formatDate(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleDateString("ru-RU") + " " + d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function dayLabel(ts) {
  if (!ts) return "Неизвестная дата";
  const d = new Date(ts * 1000);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  const day = new Date(d); day.setHours(0, 0, 0, 0);
  if (day.getTime() === today.getTime()) return "Сегодня";
  if (day.getTime() === yesterday.getTime()) return "Вчера";
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}

function dayKey(ts) {
  if (!ts) return "0";
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

const STATUS_LABEL = {
  analyzing:        "Распознаётся…",
  pending_approval: "Ожидает проверки",
  approved:         "Формируется...",
  sent:             "Заключение готово",
  error:            "Ошибка",
};
const STATUS_PILL = {
  analyzing:        "pill-analyzing",
  pending_approval: "pill-pending",
  approved:         "pill-approved",
  sent:             "pill-sent",
  error:            "pill-error",
};
const STATUS_ORDER = { analyzing: 0, pending_approval: 1, error: 2, approved: 3, sent: 4 };

let allItems = [];
let activeFilter = "all";
let activeFaculty = "all";

function isPending(r) { return r.status !== "sent"; }
function isDone(r) { return r.status === "sent"; }

function filteredItems() {
  let items = allItems;
  if (activeFilter === "pending") items = items.filter(isPending);
  else if (activeFilter === "done") items = items.filter(isDone);
  if (activeFaculty !== "all") items = items.filter(r => r.faculty === activeFaculty);
  return items;
}

function updateCounts() {
  const byFaculty = activeFaculty === "all" ? allItems : allItems.filter(r => r.faculty === activeFaculty);
  $("countAll").textContent = byFaculty.length;
  $("countPending").textContent = byFaculty.filter(isPending).length;
  $("countDone").textContent = byFaculty.filter(isDone).length;
}

function buildFacultyFilter() {
  const faculties = [...new Set(allItems.map(r => r.faculty).filter(Boolean))].sort();
  const row = $("facultyFilterRow");
  const pills = $("facultyPills");
  if (!faculties.length) { row.style.display = "none"; return; }
  row.style.display = "flex";

  pills.innerHTML = `<button class="faculty-pill active" data-faculty="all">Все (${allItems.length})</button>`;
  for (const f of faculties) {
    const count = allItems.filter(r => r.faculty === f).length;
    const btn = document.createElement("button");
    btn.className = "faculty-pill" + (f === activeFaculty ? " active" : "");
    btn.dataset.faculty = f;
    btn.textContent = `${f} (${count})`;
    pills.appendChild(btn);
  }
  if (activeFaculty === "all") pills.querySelector('[data-faculty="all"]').classList.add("active");

  pills.querySelectorAll(".faculty-pill").forEach(btn => {
    btn.addEventListener("click", () => {
      activeFaculty = btn.dataset.faculty;
      pills.querySelectorAll(".faculty-pill").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      updateCounts();
      renderList();
    });
  });
}

async function loadRequests() {
  try {
    const res = await fetch("/api/requests");
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    allItems = (data?.items || []).sort((a, b) => {
      const so = (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9);
      if (so !== 0) return so;
      return (b.created_at || 0) - (a.created_at || 0);
    });
    buildFacultyFilter();
    updateCounts();
    renderList();
  } catch (e) {
    toast("Ошибка загрузки: " + e.message, "error");
  }
}

function renderList() {
  const container = $("reqList");
  container.innerHTML = "";
  const items = filteredItems();
  $("emptyState").classList.toggle("hidden", items.length !== 0);
  if (!items.length) return;

  const pending = items.filter(isPending);
  const done = items.filter(isDone);

  if (activeFilter !== "done" && pending.length) {
    container.appendChild(makeSectionHeader("На рассмотрении", pending.length, "dot-pending"));
    container.appendChild(makeDateGroups(pending));
  }
  if (activeFilter !== "pending" && done.length) {
    container.appendChild(makeSectionHeader("Заключение готово", done.length, "dot-done"));
    container.appendChild(makeDateGroups(done));
  }
}

function makeSectionHeader(label, count, dotClass) {
  const el = document.createElement("div");
  el.className = "status-section-header";
  el.innerHTML = `
    <span class="dot ${dotClass}"></span>
    ${escapeHtml(label)}
    <span class="section-count">${count}</span>
  `;
  return el;
}

function makeDateGroups(items) {
  const wrap = document.createElement("div");
  wrap.className = "status-section";

  const groups = new Map();
  for (const r of items) {
    const k = dayKey(r.created_at);
    if (!groups.has(k)) groups.set(k, { ts: r.created_at, rows: [] });
    groups.get(k).rows.push(r);
  }
  const sorted = [...groups.values()].sort((a, b) => (b.ts || 0) - (a.ts || 0));

  for (const g of sorted) {
    const header = document.createElement("div");
    header.className = "date-group";
    header.textContent = dayLabel(g.ts);
    wrap.appendChild(header);

    const grid = document.createElement("div");
    grid.className = "req-grid";
    for (const r of g.rows) grid.appendChild(makeCard(r));
    wrap.appendChild(grid);
  }
  return wrap;
}

async function openPdfModal(url, title) {
  try {
    const r = await fetch(url, { method: "HEAD" });
    if (!r.ok) {
      toast("PDF не найден на сервере", "err");
      return;
    }
  } catch (_) {}
  document.getElementById("pdfModalFrame").src = url;
  document.getElementById("pdfModalTitle").textContent = title || "PDF";
  document.getElementById("pdfModalDownload").href = url;
  document.getElementById("pdfModalOverlay").classList.add("open");
}

function closePdfModal(e) {
  if (e.target === document.getElementById("pdfModalOverlay")) {
    document.getElementById("pdfModalOverlay").classList.remove("open");
    document.getElementById("pdfModalFrame").src = "";
  }
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const overlay = document.getElementById("pdfModalOverlay");
    if (overlay.classList.contains("open")) {
      overlay.classList.remove("open");
      document.getElementById("pdfModalFrame").src = "";
    }
  }
});

function makeCard(r) {
  const card = document.createElement("div");
  card.className = "req-card" + (r.status === "sent" ? " is-sent" : "");
  card.id = `card-${r.id}`;

  const title = escapeHtml(r.student_name || r.filename || ("Заявление #" + r.id));
  const pillClass = STATUS_PILL[r.status] || "";
  const statusLabel = STATUS_LABEL[r.status] || r.status;

  const isIntake = r.drive_file_id && r.drive_file_id.startsWith("intake_");
  const isUpload = r.drive_file_id && r.drive_file_id.startsWith("upload_");
  const intakeAppId = isIntake ? r.drive_file_id.replace("intake_", "") : null;

  const _pdfTitle = escapeHtml(JSON.stringify(r.student_name || r.filename || 'PDF'));
  const localPdfBtn = isIntake && intakeAppId
    ? `<button class="req-drive-link" onclick="openPdfModal('/api/intake/applications/${intakeAppId}/pdf', ${_pdfTitle})">Просмотр PDF</button>`
    : isUpload
    ? `<button class="req-drive-link" onclick="openPdfModal('/api/requests/${r.id}/pdf', ${_pdfTitle})">Просмотр PDF</button>`
    : "";

  const outputLink = r.status === "sent"
    ? `<a class="req-output-link" href="/api/conclusions/${r.id}/download" download>Скачать заключение →</a>`
    : "";
  const errorSnippet = r.status === "error" && r.error
    ? `<div class="req-error" title="${escapeHtml(r.error)}">${escapeHtml(r.error.slice(0, 120))}</div>`
    : "";

  // Faculty/dept badges
  const facultyBadge = r.faculty
    ? `<span class="req-faculty-tag" title="Факультет">${escapeHtml(r.faculty)}</span>`
    : "";
  const deptBadge = r.department
    ? `<span class="req-faculty-tag" title="Кафедра">${escapeHtml(r.department)}</span>`
    : "";
  const facultyRow = (facultyBadge || deptBadge)
    ? `<div class="req-faculty">${facultyBadge}${deptBadge}</div>`
    : "";

  card.innerHTML = `
    <button class="btn-delete" onclick="deleteRequest(${r.id}, event)" title="Удалить">✕</button>
    <a class="req-card-main" href="/?request=${encodeURIComponent(r.id)}">
      <div class="req-top">
        <div class="req-title">${title}</div>
        <span class="pill ${pillClass}">${escapeHtml(statusLabel)}</span>
      </div>
      <div class="req-meta">
        <div class="meta">${escapeHtml(r.group || "")}</div>
        <div class="meta">${formatDate(r.created_at)}</div>
      </div>
      ${facultyRow}
      ${errorSnippet}
    </a>
    ${(localPdfBtn || outputLink) ? `<div class="req-card-footer">${localPdfBtn}${outputLink}</div>` : ""}
  `;
  return card;
}

async function deleteRequest(id, e) {
  e.preventDefault();
  e.stopPropagation();
  if (!confirm(`Удалить заявление #${id} из очереди?`)) return;
  try {
    const res = await fetch(`/api/requests/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await res.text());
    allItems = allItems.filter(r => r.id !== id);
    buildFacultyFilter();
    updateCounts();
    renderList();
    toast("Запись удалена", "success");
  } catch (ex) {
    toast("Ошибка удаления: " + ex.message, "error");
  }
}

// Status filter tabs
document.querySelectorAll(".filter-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".filter-tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    activeFilter = btn.dataset.filter;
    updateCounts();
    renderList();
  });
});

$("refreshBtn").addEventListener("click", loadRequests);
loadRequests();

// ── SSE: живые обновления статусов очереди ────────────────────────────────
(function connectSSE() {
  const es = new EventSource("/api/queue/stream");

  es.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    if (msg.type === "heartbeat" || msg.type === "connected") return;

    if (msg.type === "added") {
      // Новая запись — добавляем в allItems если ещё нет
      if (!allItems.find(r => r.id === msg.id)) {
        allItems.push(msg);
        allItems.sort((a, b) => {
          const so = (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9);
          return so !== 0 ? so : (b.created_at || 0) - (a.created_at || 0);
        });
        buildFacultyFilter();
        updateCounts();
        renderList();
        toast(`Новое заявление: ${msg.student_name || msg.filename || "#" + msg.id}`, "success");
      }
      return;
    }

    if (msg.type === "updated") {
      const idx = allItems.findIndex(r => r.id === msg.id);
      if (idx === -1) return;
      const prev = allItems[idx];
      allItems[idx] = msg;
      allItems.sort((a, b) => {
        const so = (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9);
        return so !== 0 ? so : (b.created_at || 0) - (a.created_at || 0);
      });
      buildFacultyFilter();
      updateCounts();
      renderList();
      if (prev.status !== msg.status) {
        const label = STATUS_LABEL[msg.status] || msg.status;
        const name = msg.student_name || msg.filename || "#" + msg.id;
        toast(`${name}: ${label}`, msg.status === "error" ? "error" : "success");
      }
    }
  };

  es.onerror = () => {
    // EventSource auto-reconnects after 3s on error
  };
})();
