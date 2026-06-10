// Простое vanilla-JS приложение
const $ = (id) => document.getElementById(id);
const toast = (msg, kind = "") => {
  const t = $("toast");
  t.textContent = msg;
  t.className = `toast ${kind}`;
  setTimeout(() => t.classList.add("hidden"), 4000);
  t.classList.remove("hidden");
};

// ===== Образовательные программы =====
const PROGRAM_MAP = {
  "А": "7M08101 «Агрономия»",
  "АJ": "7M08101 «Агрономия»",
  "АГРО": "6B08101 «Агрономия»",
  "АМДИ": "6B05308 «Астрономия и методы дистанционных исследований (US)»",
  "АПО": "6B06105 «Архитектор программного обеспечения»",
  "Б": "6B01513 «Биология (IP)»",
  "БJ": "7M05101 «Биология»",
  "БМ": "6B04108 «Бизнес и менеджмент»",
  "БТ": "6B05103 «Биотехнология (US)»",
  "ВТИПО": "6B06104 «Вычислительная техника и программное обеспечение»",
  "Г": "6B01518 «География (IP)»",
  "ГJ": "7M05201 «География»",
  "ГИП": "6B05203 «География и природопользование»",
  "ДА": "7M04102 «Деловое администрирование(MBA)»",
  "ДЗ": "6B02101 «Дизайн»",
  "ДОВ": "6B01201 «Дошкольное обучение и воспитание»",
  "Ж": "7M03201 «Журналистика»",
  "ЖJ": "7M03201 «Журналистика»",
  "И": "7M02201 «История»",
  "ИВТУ": "8D06101 «Информатика, вычислительная техника и управление»",
  "ИВТУI": "8D06102 «Информатика, вычислительная техника и управление»",
  "ИВТУJ": "8D06101 «Информатика, вычислительная техника и управление»",
  "ИИИТ": "6B07504 «Инжиниринг и инновационно-измерительные технологии»",
  "ИН": "6B01517 «Информатика (IP)»",
  "ИО": "6B01602 «История и обществознание (IP)»",
  "ИС": "6B06102 «Информационные системы»",
  "ИСJ": "7M06102 «Информационные системы»",
  "ИСУ": "6B06106 «Информационные системы в управлении»",
  "ИФ": "6B02302 «Иностранная филология»",
  "ИЯ": "7M01701 «Иностранный язык: два иностранных языка»",
  "ИЯJ": "7M01701 «Иностранный язык: два иностранных языка»",
  "КДР": "6B11101 «Культурно-досуговая работа»",
  "КЯЛ": "6B01706 «Казахский язык и литература (IP)»",
  "КЯЛJ": "7M01705 «Казахский язык и литература»",
  "ЛРЛ": "6B08301 «Лесные ресурсы и лесоводство»",
  "М": "6B01516 «Математика (IP)»",
  "МЕ": "7M04104 «Менеджмент»",
  "МЕJ": "7M04104 «Менеджмент»",
  "МЕД": "6B10104 «Медицина»",
  "МИ": "6B01508 «Математика-Информатика»",
  "МО": "6B01406 «Музыкальное образование (IP)»",
  "МС": "8D07101 «Машиностроение»",
  "МСI": "8D07106 «Машиностроение»",
  "МСJ": "7M07101 «Машиностроение»",
  "МСJI": "8D07106 «Машиностроение»",
  "МФ": "6B01509 «Математика-Физика»",
  "НО": "6B01303 «Начальное образование (IP)»",
  "НОИП": "6B01302 «Начальное образование и инклюзивная практика (US)»",
  "НРТ": "6B08104 «Наука о растениях и технологии (US)»",
  "ОМ": "6B10101 «Общая медицина»",
  "ПВО": "6B01103 «Психология в образовании»",
  "ПД": "6B02303 «Переводческое дело»",
  "ПИМСО": "6B07302 «Проектирование и информационное моделирование строительных объектов»",
  "ПМНО": "6B01301 «Педагогика и методика начального обучения»",
  "ППС": "7M01101 «Педагогика и психология»",
  "ППСJ": "7M01101 «Педагогика и психология»",
  "РИС": "6B07109 «Робототехнические и интеллектуальные системы»",
  "РИСП": "7M07106 «Робототехнические, интеллектуальные системы и приборостроение»",
  "РИСПJ": "7M07106 «Робототехнические, интеллектуальные системы и приборостроение»",
  "РИТМ": "6B07108 «Робототехника и инновационные технологии в машиностроении»",
  "РЛ": "6B01705 «Русский язык и литература в школах с русским и нерусским языками обучения (IP)»",
  "РЭТ": "8D06201 «Радиотехника, электроника и телекоммуникации»",
  "С": "6B07301 «Строительство»",
  "СОЦП": "6B01802 «Социальная педагогика»",
  "СП": "6B01908 «Специальная педагогика (IP)»",
  "СПJ": "7M01903 «Специальная педагогика»",
  "СПИП": "6B01907 «Специальная педагогика и инклюзивная практика (US)»",
  "ССI": "7M07504 «Стандартизация и сертификация (по отраслям)»",
  "ССМ": "7M07502 «Стандартизация, сертификация и метрология (по отраслям)»",
  "ССМJ": "7M07502 «Стандартизация, сертификация и метрология (по отраслям)»",
  "Т": "6B11102 «Туризм»",
  "ТПП": "6B07201 «Технология продовольственных продуктов»",
  "ТППЖ": "7M08201 «Технология производства продуктов животноводства»",
  "ТР": "8D07105 «Транспорт, транспортная техника и технологии»",
  "ТРJ": "8D07105 «Транспорт, транспортная техника и технологии»",
  "ТЭОРВ": "6B07107 «Техническая эксплуатация, обслуживание и ремонт вагонов»",
  "УИА": "6B04105 «Учет и аудит»",
  "Ф": "6B01515 «Физика (IP)»",
  "ФА": "7M04108 «Финансовая аналитика»",
  "ФАРМ": "6B10102 «Фармация»",
  "ФИ": "6B01510 «Физика-Информатика»",
  "ФИЛ": "7M02301 «Филология»",
  "ФКНВП": "6B01404 «Физическая культура и начальная военная подготовка»",
  "ФКС": "6B01405 «Физическая культура и спорт (IP)»",
  "ФС": "6B04104 «Финансы»",
  "Х": "6B01519 «Химия (IP)»",
  "ХJ": "7M01504 «Химия»",
  "ХБ": "6B01511 «Химия-Биология»",
  "ХТОВ": "8D07102 «Химическая технология органических веществ»",
  "ХТОВI": "8D07107 «Химическая технология органических веществ»",
  "ХЭАКП": "6B05307 «Химическая экспертиза и аналитический контроль производства (US)»",
  "Э": "8D04101 «Экономика»",
  "ЭJ": "8D04101 «Экономика»",
  "ЭИТ": "6B06203 «Электроника и телекоммуникации»",
  "ЭКОЛ": "7M05202 «Экология»",
  "ЭЭ": "8D07103 «Электроэнергетика»",
  "ЭЭI": "7M07115 «Электроэнергетика»",
  "ЭЭJ": "8D07103 «Электроэнергетика»",
  "Ю": "7M04201 «Юриспруденция»",
  "ЮI": "7M04202 «Юриспруденция»",
  "ЮIJ": "7M04202 «Юриспруденция»",
  "ЮJ": "7M04201 «Юриспруденция»",
};
// Уникальные названия для дропдауна
const PROGRAMS = [...new Set(Object.values(PROGRAM_MAP))].sort();

function deriveProgram(group) {
  if (!group) return "";
  const m = group.trim().match(/^([А-Яа-яёЁA-Za-z]+)/u);
  if (!m) return "";
  return PROGRAM_MAP[m[1].toUpperCase()] || "";
}

// ===== Combobox helper =====
function initCombobox(container, getOptions, onChange) {
  const input = container.querySelector(".cb-input");
  const dropdown = container.querySelector(".cb-dropdown");
  function renderDropdown() {
    const q = input.value.trim().toLowerCase();
    const opts = getOptions();
    const filtered = q ? opts.filter(o => o.toLowerCase().includes(q)) : opts;
    if (filtered.length === 0) { dropdown.classList.add("hidden"); return; }
    dropdown.innerHTML = "";
    filtered.slice(0, 40).forEach(opt => {
      const item = document.createElement("div");
      item.className = "cb-item";
      item.textContent = opt;
      item.addEventListener("mousedown", e => {
        e.preventDefault();
        input.value = opt;
        dropdown.classList.add("hidden");
        if (onChange) onChange(opt);
      });
      dropdown.appendChild(item);
    });
    dropdown.classList.remove("hidden");
  }
  input.addEventListener("focus", renderDropdown);
  input.addEventListener("input", () => { renderDropdown(); if (onChange) onChange(input.value.trim()); });
  input.addEventListener("blur", () => { setTimeout(() => dropdown.classList.add("hidden"), 160); });
  return {
    getValue: () => input.value.trim(),
    setValue: (v) => { input.value = v; },
  };
}

const cbProgram = initCombobox($("cb-program"), () => PROGRAMS);

// Автозаполнение ОП по коду группы
$("fGroup").addEventListener("input", () => {
  const derived = deriveProgram($("fGroup").value);
  if (derived) cbProgram.setValue(derived);
});

const state = {
  certificates: [],     // [{page, course_title, provider, hours, grade, date, _bound: discIdx|null, _id}]
  disciplines: [],      // [{name, plan_credits, total_hours, grade_points, compliance, note, final_grade}]
  student: { name: "", group: "", program_code: "", course_year: "" },
};

let nextCertId = 1;
let activeRequestId = null; // если открыто из очереди /approve

// ===== Step 1: upload =====
const dz = $("dropzone");
const pdfInput = $("pdfInput");
const analyzeBtn = $("analyzeBtn");
const uploadMeta = $("uploadMeta");

let chosenFile = null;

["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, e => {
  e.preventDefault();
  dz.classList.add("over");
}));
["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => {
  e.preventDefault();
  dz.classList.remove("over");
}));
dz.addEventListener("drop", e => {
  const f = e.dataTransfer.files[0];
  if (f) handleFile(f);
});
pdfInput.addEventListener("change", e => {
  const f = e.target.files[0];
  if (f) handleFile(f);
});
function handleFile(f) {
  if (!f.name.toLowerCase().endsWith(".pdf")) {
    toast("Нужен .pdf файл", "error");
    return;
  }
  chosenFile = f;
  uploadMeta.textContent = `${f.name} · ${(f.size / 1024).toFixed(0)} KB`;
  analyzeBtn.disabled = false;
}

analyzeBtn.addEventListener("click", async () => {
  if (!chosenFile) return;
  const fd = new FormData();
  fd.append("pdf", chosenFile);
  const orKey = $("openrouterKey").value.trim();
  const geminiKey = $("apiKey").value.trim();
  if (orKey) fd.append("openrouter_api_key", orKey);
  if (geminiKey) fd.append("gemini_api_key", geminiKey);
  fd.append("auto_map", "true");

  $("step-upload").classList.add("hidden");
  $("step-loading").classList.remove("hidden");
  $("loadingText").textContent = `Распознаём документ (страниц: ?) — это занимает 30–90 сек…`;

  try {
    const res = await fetch("/api/analyze", { method: "POST", body: fd });
    if (!res.ok) {
      const errText = (await res.json().catch(() => null))?.detail || res.statusText;
      throw new Error(errText);
    }
    const data = await res.json();
    populateFromAnalyze(data);
    $("step-loading").classList.add("hidden");
    $("step-editor").classList.remove("hidden");
    if (Array.isArray(data.errors) && data.errors.length) {
      toast(`Распознано с замечаниями (${data.errors.length}): ${data.errors[0]}`, "error");
      console.warn("Analyze warnings:", data.errors);
    }
  } catch (e) {
    toast("Ошибка анализа: " + e.message, "error");
    $("step-loading").classList.add("hidden");
    $("step-upload").classList.remove("hidden");
  }
});

// ===== Load from queue by ?request=ID =====
async function maybeLoadFromQueue() {
  const params = new URLSearchParams(location.search);
  const rid = params.get("request");
  if (!rid) return;
  activeRequestId = rid;

  // в режиме апрува шаг загрузки скрываем
  $("step-upload").classList.add("hidden");
  $("step-loading").classList.remove("hidden");
  $("loadingText").textContent = "Загружаем распознанные данные из очереди…";
  try {
    const res = await fetch(`/api/requests/${encodeURIComponent(rid)}`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    populateFromAnalyze(data.analyze);
    if (data.edit) applyEditState(data.edit);
    showQueueDriveLink(data);
    $("step-loading").classList.add("hidden");
    $("step-editor").classList.remove("hidden");
    injectApproveControls();
  } catch (e) {
    toast("Не удалось загрузить заявку: " + e.message, "error");
    $("step-loading").classList.add("hidden");
    $("step-upload").classList.remove("hidden");
    activeRequestId = null;
  }
}

function showQueueDriveLink(data) {
  const head = document.querySelector("#step-editor .step-head");
  if (!head) return;
  head.querySelector(".queue-drive-link")?.remove();
  const url = data.drive_file_url || (
    data.drive_file_id
      ? `https://drive.google.com/file/d/${encodeURIComponent(data.drive_file_id)}/view`
      : ""
  );
  if (!url) return;
  const a = document.createElement("a");
  a.className = "queue-drive-link";
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.textContent = "Исходный PDF на Google Drive";
  head.appendChild(a);
}

function applyEditState(edit) {
  if (!edit) return;
  if (edit.student) {
    $("fStudent").value = edit.student.name ?? $("fStudent").value;
    $("fGroup").value = edit.student.group ?? $("fGroup").value;
    $("fProgram").value = edit.student.program_code ?? $("fProgram").value;
    $("fYear").value = edit.student.course_year ?? $("fYear").value;
  }
  if (Array.isArray(edit.disciplines)) {
    state.disciplines = edit.disciplines.map((d) => ({
      name: d.name ?? "",
      plan_credits: d.plan_credits ?? "5",
      total_hours: d.total_hours ?? "",
      grade_points: d.grade_points ?? "",
      compliance: d.compliance ?? "полное",
      note: d.note ?? "",
      final_grade: d.final_grade ?? "",
    }));
  }
  if (Array.isArray(edit.certificates)) {
    state.certificates = edit.certificates.map((c) => ({
      page: c.page ?? 0,
      course_title: c.course_title ?? "",
      provider: c.provider ?? "",
      hours: c.hours ?? "",
      grade: c.grade ?? "",
      date: c.date ?? "",
      verify_url: c.verify_url ?? "",
      _bound: c._bound ?? null,
      _id: nextCertId++,
    }));
  }
  render();
}

function currentEditState() {
  return {
    student: {
      name: $("fStudent").value.trim(),
      group: $("fGroup").value.trim(),
      program_code: $("fProgram").value.trim(),
      course_year: $("fYear").value.trim(),
    },
    disciplines: state.disciplines.map((d) => ({ ...d })),
    certificates: state.certificates.map((c) => ({
      page: c.page,
      course_title: c.course_title,
      provider: c.provider,
      hours: c.hours,
      grade: c.grade,
      date: c.date,
      verify_url: c.verify_url || "",
      _bound: c._bound,
    })),
  };
}

async function saveQueueEditState() {
  if (!activeRequestId) return;
  const payload = currentEditState();
  const res = await fetch(`/api/requests/${encodeURIComponent(activeRequestId)}/edit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
}

function injectApproveControls() {
  // добавляем кнопки "Сохранить" + "Апрув" рядом с Generate
  const actions = document.querySelector("#step-editor .actions.actions-right");
  if (!actions || actions.dataset.hasApprove === "1") return;
  actions.dataset.hasApprove = "1";

  const reanalyzeBtn = document.createElement("button");
  reanalyzeBtn.className = "btn-ghost";
  reanalyzeBtn.textContent = "Распознать заново";
  reanalyzeBtn.addEventListener("click", async () => {
    if (!activeRequestId) return;
    if (!confirm(
      "Заново распознать PDF с Google Drive?\n\nТекущие правки в форме будут заменены (30–90 сек)."
    )) return;
    reanalyzeBtn.disabled = true;
    $("step-editor").classList.add("hidden");
    $("step-loading").classList.remove("hidden");
    $("loadingText").textContent = "Повторное распознавание PDF с Drive…";
    try {
      const res = await fetch(
        `/api/requests/${encodeURIComponent(activeRequestId)}/reanalyze`,
        { method: "POST" }
      );
      if (!res.ok) {
        const err = (await res.json().catch(() => null))?.detail || await res.text();
        throw new Error(err);
      }
      const data = await res.json();
      nextCertId = 1;
      populateFromAnalyze(data.analyze);
      if (data.edit) applyEditState(data.edit);
      $("step-loading").classList.add("hidden");
      $("step-editor").classList.remove("hidden");
      if (data.errors?.length) {
        toast(`Распознано с замечаниями: ${data.errors[0]}`, "error");
      } else {
        toast("Распознавание обновлено", "success");
      }
    } catch (e) {
      toast("Ошибка распознавания: " + e.message, "error");
      $("step-loading").classList.add("hidden");
      $("step-editor").classList.remove("hidden");
    } finally {
      reanalyzeBtn.disabled = false;
    }
  });

  const saveBtn = document.createElement("button");
  saveBtn.className = "btn-ghost";
  saveBtn.textContent = "Сохранить черновик";
  saveBtn.addEventListener("click", async () => {
    try {
      await saveQueueEditState();
      toast("Сохранено", "success");
    } catch (e) {
      toast("Ошибка сохранения: " + e.message, "error");
    }
  });

  const approveBtn = document.createElement("button");
  approveBtn.className = "btn-primary";
  approveBtn.textContent = "Апрув + отправить в Drive";
  approveBtn.addEventListener("click", async () => {
    try {
      await saveQueueEditState();
      const res = await fetch(`/api/requests/${encodeURIComponent(activeRequestId)}/approve`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(await res.text());
      toast("Отправлено в Google Drive", "success");
      setTimeout(() => (location.href = "/approve"), 700);
    } catch (e) {
      toast("Ошибка апрува: " + e.message, "error");
    }
  });

  actions.insertBefore(reanalyzeBtn, $("generateBtn"));
  actions.insertBefore(saveBtn, $("generateBtn"));
  actions.insertBefore(approveBtn, $("generateBtn"));
}

// ===== Populate editor =====
function populateFromAnalyze(data) {
  state.student = {
    name: data.student_name || "",
    group: data.group || "",
    program_code: data.program_code || "",
    course_year: data.course_year || "",
  };
  $("fStudent").value = state.student.name;
  $("fGroup").value = state.student.group;
  $("fProgram").value = state.student.program_code;
  $("fYear").value = state.student.course_year;

  state.disciplines = (data.disciplines || []).map(d => ({
    name: d,
    plan_credits: "5",
    total_hours: "",
    grade_points: "",
    compliance: "полное",
    note: "",
    final_grade: "",
  }));
  state.certificates = (data.certificates || []).map(c => ({
    ...c,
    _bound: null,
    _id: nextCertId++,
  }));

  // apply auto-mapping
  const m = data.mapping || {};
  for (const [certIdxStr, discIdx] of Object.entries(m)) {
    const ci = parseInt(certIdxStr, 10);
    if (state.certificates[ci] && discIdx >= 0 && discIdx < state.disciplines.length) {
      state.certificates[ci]._bound = discIdx;
    }
  }
  render();
}

// ===== Render =====
function render() {
  renderPool();
  renderDisciplines();
}

function renderPool() {
  const pool = $("certPool");
  pool.innerHTML = "";
  state.certificates.forEach((c, i) => {
    if (c._bound !== null) return;
    pool.appendChild(makeCertCard(c, i));
  });
}

function makeCertCard(c, idx) {
  const card = document.createElement("div");
  card.className = "cert-card";
  card.draggable = true;
  card.dataset.idx = idx;

  const verifyLink = c.verify_url
    ? `<a class="cert-verify-link" href="${escapeHtml(c.verify_url)}" target="_blank" rel="noopener noreferrer" title="Проверить подлинность">✓ Проверить</a>`
    : "";

  card.innerHTML = `
    <span class="cert-page-badge">стр. ${c.page}</span>
    <div class="cert-actions">
      <button class="cert-link-btn" data-act="bind">→ дисциплина</button>
    </div>
    <div class="cert-content">
      <div class="cert-title" contenteditable="true">${escapeHtml(c.course_title)}</div>
      <div class="cert-meta">
        <span class="pill" contenteditable="true" data-f="provider">${escapeHtml(c.provider || "—")}</span>
        <span class="pill" contenteditable="true" data-f="hours">${escapeHtml(c.hours || "—")}</span>
        ${c.grade ? `<span class="pill" contenteditable="true" data-f="grade">${escapeHtml(c.grade)}</span>` : ""}
        ${verifyLink}
      </div>
    </div>
  `;

  card.addEventListener("dragstart", e => {
    card.classList.add("dragging");
    e.dataTransfer.setData("text/plain", String(idx));
    e.dataTransfer.effectAllowed = "move";
  });
  card.addEventListener("dragend", () => card.classList.remove("dragging"));

  card.querySelector(".cert-title").addEventListener("input", e => {
    state.certificates[idx].course_title = e.target.textContent;
  });
  card.querySelectorAll("[data-f]").forEach(el => {
    el.addEventListener("input", e => {
      const f = el.dataset.f;
      state.certificates[idx][f] = el.textContent.replace(/^—$/, "");
    });
  });

  card.querySelector('[data-act="bind"]').addEventListener("click", () => {
    if (state.disciplines.length === 0) {
      toast("Сначала добавьте дисциплину", "error");
      return;
    }
    const choices = state.disciplines.map((d, i) => `${i + 1}. ${d.name || "(без названия)"}`).join("\n");
    const ans = prompt(`Привязать к какой дисциплине? Введите номер 1-${state.disciplines.length}:\n\n${choices}`);
    const n = parseInt(ans, 10);
    if (!isNaN(n) && n >= 1 && n <= state.disciplines.length) {
      state.certificates[idx]._bound = n - 1;
      render();
    }
  });
  return card;
}

function renderDisciplines() {
  const wrap = $("disciplineList");
  wrap.innerHTML = "";
  state.disciplines.forEach((d, i) => {
    const block = document.createElement("div");
    block.className = "discipline";
    block.dataset.idx = i;
    block.innerHTML = `
      <div class="discipline-head">
        <span class="idx">${i + 1}</span>
        <input class="disc-name" type="text" value="${escapeAttr(d.name)}" placeholder="Название дисциплины">
        <button class="btn-danger-ghost" data-act="del">Удалить</button>
      </div>
      <div class="discipline-fields">
        <div class="field"><label>Кредитов по плану</label><input type="text" data-f="plan_credits" value="${escapeAttr(d.plan_credits)}"></div>
        <div class="field"><label>Итого часов</label><input type="text" data-f="total_hours" value="${escapeAttr(d.total_hours)}" placeholder="авто"></div>
        <div class="field"><label>Баллы</label><input type="text" data-f="grade_points" value="${escapeAttr(d.grade_points)}"></div>
        <div class="field"><label>Соответствие</label><input type="text" data-f="compliance" value="${escapeAttr(d.compliance)}"></div>
        <div class="field"><label>Примечание</label><input type="text" data-f="note" value="${escapeAttr(d.note)}"></div>
        <div class="field"><label>Зачтённая оценка</label><input type="text" data-f="final_grade" value="${escapeAttr(d.final_grade)}" placeholder="напр. 75 (С)"></div>
      </div>
      <div class="discipline-drop" data-disc-idx="${i}"></div>
    `;

    block.querySelector(".disc-name").addEventListener("input", e => {
      state.disciplines[i].name = e.target.value;
    });
    block.querySelectorAll(".discipline-fields [data-f]").forEach(inp => {
      inp.addEventListener("input", e => {
        state.disciplines[i][inp.dataset.f] = e.target.value;
      });
    });
    block.querySelector('[data-act="del"]').addEventListener("click", () => {
      state.certificates.forEach(c => {
        if (c._bound === i) c._bound = null;
        else if (c._bound !== null && c._bound > i) c._bound -= 1;
      });
      state.disciplines.splice(i, 1);
      render();
    });

    const drop = block.querySelector(".discipline-drop");
    drop.addEventListener("dragover", e => {
      e.preventDefault();
      drop.classList.add("over");
    });
    drop.addEventListener("dragleave", () => drop.classList.remove("over"));
    drop.addEventListener("drop", e => {
      e.preventDefault();
      drop.classList.remove("over");
      const idx = parseInt(e.dataTransfer.getData("text/plain"), 10);
      if (!isNaN(idx)) {
        state.certificates[idx]._bound = i;
        render();
      }
    });

    state.certificates.forEach((c, idx) => {
      if (c._bound !== i) return;
      const card = makeCertCard(c, idx);
      const unbind = document.createElement("button");
      unbind.className = "btn-danger-ghost";
      unbind.style.cssText = "position:absolute;top:8px;right:8px;font-size:11px;";
      unbind.textContent = "Открепить";
      unbind.addEventListener("click", () => {
        state.certificates[idx]._bound = null;
        render();
      });
      card.querySelector(".cert-actions").replaceWith(unbind);
      drop.appendChild(card);
    });

    wrap.appendChild(block);
  });
}

$("addDisciplineBtn").addEventListener("click", () => {
  state.disciplines.push({
    name: "",
    plan_credits: "5",
    total_hours: "",
    grade_points: "",
    compliance: "полное",
    note: "",
    final_grade: "",
  });
  render();
});

// ===== Generate =====
$("generateBtn").addEventListener("click", async () => {
  const payload = {
    student_name: $("fStudent").value.trim(),
    program_code: $("fProgram").value.trim(),
    course_year: $("fYear").value.trim(),
    rows: state.disciplines.map((d, i) => ({
      discipline: d.name,
      plan_credits: d.plan_credits,
      total_hours: d.total_hours,
      grade_points: d.grade_points,
      compliance: d.compliance,
      note: d.note,
      final_grade: d.final_grade,
      courses: state.certificates
        .filter(c => c._bound === i)
        .map(c => ({
          course_title: c.course_title,
          provider: c.provider,
          hours: c.hours,
          grade: c.grade,
          date: c.date,
        })),
    })),
  };

  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(t);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const dispo = res.headers.get("Content-Disposition") || "";
    const m = dispo.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/);
    a.href = url;
    a.download = m ? decodeURIComponent(m[1]) : "report.docx";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast("Документ создан", "success");
  } catch (e) {
    toast("Ошибка генерации: " + e.message, "error");
  }
});

$("backBtn").addEventListener("click", () => {
  $("step-editor").classList.add("hidden");
  $("step-upload").classList.remove("hidden");
});

// ===== Helpers =====
function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
function escapeAttr(s) { return escapeHtml(s); }

// Восстанавливаем ключи из localStorage
const savedGemini = localStorage.getItem("gemini_key");
if (savedGemini) $("apiKey").value = savedGemini;
$("apiKey").addEventListener("change", () => {
  localStorage.setItem("gemini_key", $("apiKey").value.trim());
});
const savedOR = localStorage.getItem("openrouter_key");
if (savedOR) $("openrouterKey").value = savedOR;
$("openrouterKey").addEventListener("change", () => {
  localStorage.setItem("openrouter_key", $("openrouterKey").value.trim());
});

// init
maybeLoadFromQueue();
