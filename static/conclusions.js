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

async function loadConclusions() {
  try {
    const res = await fetch("/api/conclusions");
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    renderList(data.items || []);
  } catch (e) {
    toast("Ошибка загрузки: " + e.message, "error");
  }
}

function renderList(items) {
  const list = $("concList");
  list.innerHTML = "";
  $("emptyState").classList.toggle("hidden", items.length !== 0);

  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "conc-card";

    const downloadLink = item.has_local_file
      ? `<a class="btn-primary" href="/api/conclusions/${item.id}/download" download
            style="font-size:13px;text-decoration:none;padding:6px 14px;">Скачать DOCX</a>`
      : `<span class="meta" style="font-size:12px;">Файл не найден</span>`;

    const sourceTag = item.filename && item.filename.startsWith("Заявление_")
      ? `<span class="source-tag">из формы</span>`
      : `<span class="source-tag" style="background:#f1f5f9;color:#475569;">загружен вручную</span>`;

    const meta = [];
    if (item.group) meta.push(`Группа: <b>${escapeHtml(item.group)}</b>`);
    if (item.faculty) meta.push(`Ф-т: <b>${escapeHtml(item.faculty)}</b>`);
    if (item.department) meta.push(`Каф.: <b>${escapeHtml(item.department)}</b>`);
    meta.push(`Создано: ${formatDate(item.created_at)}`);
    meta.push(`Готово: ${formatDate(item.updated_at)}`);

    card.innerHTML = `
      <div class="conc-card-top">
        <div class="conc-card-title">${escapeHtml(item.student_name || "Студент #" + item.id)}</div>
        <div style="display:flex;gap:6px;align-items:center;">
          ${sourceTag}
          <span class="pill pill-sent">Готово</span>
        </div>
      </div>
      <div class="conc-card-meta">
        ${meta.map(m => `<span>${m}</span>`).join("")}
      </div>
      <div class="conc-card-actions">
        ${downloadLink}
      </div>
    `;
    list.appendChild(card);
  });
}

$("refreshBtn").addEventListener("click", loadConclusions);
loadConclusions();
