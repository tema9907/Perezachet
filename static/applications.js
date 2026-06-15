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

const STATUS_LABEL = { created: "Создано", in_review: "На экспертизе", done: "Заключение готово" };
const STATUS_PILL  = { created: "pill-created", in_review: "pill-in_review", done: "pill-done" };

let allApps = [];

async function loadApps() {
  try {
    const res = await fetch("/api/intake/applications");
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    allApps = data.items || [];
    renderList(allApps);
  } catch (e) {
    toast("Ошибка загрузки: " + e.message, "error");
  }
}

function renderList(apps) {
  const list = $("appList");
  list.innerHTML = "";
  $("emptyState").classList.toggle("hidden", apps.length !== 0);

  apps.forEach((app) => {
    const card = document.createElement("div");
    card.className = "app-card";
    const pillClass = STATUS_PILL[app.status] || "pill";
    const statusLabel = STATUS_LABEL[app.status] || app.status;

    const subjPreview = (app.subjects || []).slice(0, 4)
      .map(s => `<li title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</li>`).join("") +
      (app.subjects?.length > 4 ? `<li>+${app.subjects.length - 4} ещё</li>` : "");

    const driveLink = `<a class="btn-ghost" href="/api/intake/applications/${app.id}/pdf"
          target="_blank" rel="noopener noreferrer" style="font-size:13px;">Просмотр PDF</a>`;
    const expertLink = app.queue_request_id && app.status === "done"
      ? `<a class="btn-ghost" href="/api/conclusions/${app.queue_request_id}/download" download
            style="font-size:13px;color:var(--success,#16a34a);">Скачать заключение →</a>`
      : "";

    card.innerHTML = `
      <div class="app-card-top">
        <div class="app-card-title">${escapeHtml(app.student_name || "Без имени")}</div>
        <span class="pill ${pillClass}">${escapeHtml(statusLabel)}</span>
      </div>
      <div class="app-card-meta">
        ${app.faculty ? `<span title="Факультет студента">Ф-т студента: <b>${escapeHtml(app.faculty)}</b></span>` : ""}
        ${app.department ? `<span title="Кафедра студента">Каф. студента: <b>${escapeHtml(app.department)}</b></span>` : ""}
        ${app.group_name ? `<span>Группа: <b>${escapeHtml(app.group_name)}</b></span>` : ""}
        ${app.course_year ? `<span>Курс: ${escapeHtml(app.course_year)}</span>` : ""}
        <span>Дата: ${formatDate(app.created_at)}</span>
      </div>
      ${subjPreview ? `<ul class="subjects-list">${subjPreview}</ul>` : ""}
      <div class="app-card-actions">
        <button class="btn-ghost" onclick="openModal(${app.id})">Просмотр</button>
        ${driveLink}
        ${expertLink}
        ${app.status === "created"
          ? `<button class="btn-primary" onclick="sendToReview(${app.id}, this)">Отправить на экспертизу</button>`
          : ""}
      </div>
    `;
    list.appendChild(card);
  });
}

async function sendToReview(appId, btn) {
  if (!confirm("Отправить заявление в очередь экспертной проверки?")) return;
  btn.disabled = true;
  btn.textContent = "Отправляем…";
  try {
    const res = await fetch(`/api/intake/applications/${appId}/send-to-review`, { method: "POST" });
    if (!res.ok) throw new Error(await res.text());
    toast("Заявление отправлено на экспертизу", "success");
    await loadApps();
  } catch (e) {
    toast("Ошибка: " + e.message, "error");
    btn.disabled = false;
    btn.textContent = "Отправить на экспертизу";
  }
}

function openModal(appId) {
  const app = allApps.find(a => a.id === appId);
  if (!app) return;

  $("modalTitle").textContent = app.student_name || "Заявление #" + app.id;

  // Timeline
  const steps = ["created", "in_review", "done"];
  const order = steps.indexOf(app.status);
  document.querySelectorAll(".timeline-step").forEach((el, i) => {
    el.classList.remove("active", "done-step");
    if (i < order) el.classList.add("done-step");
    else if (i === order) el.classList.add("active");
  });

  const body = $("modalBody");
  const subjRows = (app.subjects || []).map((s, i) => {
    const certs = (s.certs || []).filter(c => c.source).map(c => escapeHtml(c.source)).join(", ");
    const ownerDep = [s.faculty, s.department].filter(Boolean).join(" → ");
    const noDept = !s.department;
    return `
      <div class="modal-subj-row">
        <div class="modal-subj-name">${i + 1}. ${escapeHtml(s.name || "—")}</div>
        <div class="modal-subj-meta" style="color:${noDept ? "var(--danger,#dc2626)" : ""};">
          Кафедра-держатель: ${ownerDep ? escapeHtml(ownerDep) : "<i>не указана</i>"}
        </div>
        ${certs ? `<div class="modal-subj-meta">Источники: ${certs}</div>` : ""}
      </div>`;
  }).join("");

  const pdfUrl = `/api/intake/applications/${app.id}/pdf`;
  const expertConclusionId = app.queue_request_id && app.status === "done" ? app.queue_request_id : null;

  body.innerHTML = `
    <div class="modal-section">
      <h3>Данные студента <span style="font-size:11px;font-weight:400;color:var(--muted);">(заявление подаётся сюда)</span></h3>
      <div class="modal-field"><span class="modal-field-label">ФИО:</span><span>${escapeHtml(app.student_name)}</span></div>
      <div class="modal-field"><span class="modal-field-label">Факультет:</span><span>${escapeHtml(app.faculty || "—")}</span></div>
      <div class="modal-field"><span class="modal-field-label">Кафедра студента:</span><span>${escapeHtml(app.department || "—")}</span></div>
      <div class="modal-field"><span class="modal-field-label">Группа:</span><span>${escapeHtml(app.group_name || "—")}</span></div>
      <div class="modal-field"><span class="modal-field-label">Курс:</span><span>${escapeHtml(app.course_year || "—")}</span></div>
      <div class="modal-field"><span class="modal-field-label">Телефон:</span><span>${escapeHtml(app.phone || "—")}</span></div>
      <div class="modal-field"><span class="modal-field-label">Создано:</span><span>${formatDate(app.created_at)}</span></div>
    </div>
    <div class="modal-section">
      <h3>Предметы для перезачёта (${(app.subjects || []).length}) <span style="font-size:11px;font-weight:400;color:var(--muted);">— заключения утверждают кафедры-держатели</span></h3>
      ${subjRows || "<p class='meta'>Нет предметов</p>"}
    </div>
    <div class="modal-section"><h3>Документы</h3>
      <a class="btn-ghost" href="${escapeHtml(pdfUrl)}" target="_blank" rel="noopener noreferrer">Просмотр PDF заявления →</a>
    </div>
    ${expertConclusionId ? `<div class="modal-section"><h3>Экспертное заключение</h3>
      <a class="btn-ghost" style="color:var(--success,#16a34a);" href="/api/conclusions/${expertConclusionId}/download" download>Скачать заключение (DOCX) →</a>
    </div>` : ""}
    ${app.status === "in_review" ? `<p class="meta" style="margin-top:12px;">Заявление передано эксперту. Когда заключение будет готово, ссылка появится здесь.</p>` : ""}
    ${app.status === "created"
      ? `<div style="margin-top:16px;">
           <button class="btn-primary" onclick="sendToReview(${app.id}, this)">Отправить на экспертизу</button>
         </div>`
      : ""}
  `;

  $("modalOverlay").classList.add("open");
}

$("modalClose").addEventListener("click", () => $("modalOverlay").classList.remove("open"));
$("modalOverlay").addEventListener("click", (e) => {
  if (e.target === $("modalOverlay")) $("modalOverlay").classList.remove("open");
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("modalOverlay").classList.remove("open");
});

$("refreshBtn").addEventListener("click", loadApps);
loadApps();

// ── Авто-поллинг статусов ──────────────────────────────────────────────────
function hasActiveApps(apps) {
  return apps.some(a => a.status === "in_review");
}

async function pollApps() {
  try {
    const res = await fetch("/api/intake/applications");
    if (!res.ok) return;
    const data = await res.json();
    const newApps = data.items || [];

    // Проверяем изменения по статусам
    let changed = newApps.length !== allApps.length;
    if (!changed) {
      for (const a of newApps) {
        const old = allApps.find(o => o.id === a.id);
        if (!old || old.status !== a.status) { changed = true; break; }
      }
    }
    if (changed) {
      const prevApps = allApps;
      allApps = newApps;
      renderList(allApps);
      // Тост только если реально что-то стало готово
      for (const a of newApps) {
        const old = prevApps.find(o => o.id === a.id);
        if (old && old.status === "in_review" && a.status === "done") {
          toast(`Заключение по заявлению «${a.student_name}» готово`, "success");
        }
      }
    }
  } catch {}
}

// Поллинг с адаптивным интервалом: быстрее если есть активные заявления
let _pollTimer = null;
function schedulePoll() {
  clearTimeout(_pollTimer);
  const delay = hasActiveApps(allApps) ? 4000 : 15000;
  _pollTimer = setTimeout(async () => {
    await pollApps();
    schedulePoll();
  }, delay);
}
schedulePoll();

// При ручном обновлении — сбрасываем таймер
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) schedulePoll();
});
