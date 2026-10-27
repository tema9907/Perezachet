// Пошаговый туториал по генератору экспертного заключения.
// Использует $, toast, state, render, populateFromAnalyze из app.js — подключать после него.
// На время тура страница неактивна (inert), редактор заполняется демо-данными,
// а после выхода всё, что было на странице, восстанавливается.
(function () {
  const TOPBAR = 56; // высота липкой шапки
  const GAP = 16;
  const PAD = 6;     // отступ подсветки вокруг элемента

  const SECTIONS = ["step-upload", "step-loading", "step-editor"];
  const FIELDS = ["fStudent", "fGroup", "fProgram", "fYear"];

  const DEMO = {
    student_name: "Иванов Иван Иванович",
    group: "ВТИПО-22",
    program_code: "6B06104 «Вычислительная техника и программное обеспечение»",
    course_year: "3",
    disciplines: ["Программирование на Python", "Базы данных"],
    plan_data: {
      "Программирование на Python": { credits: 5, lec: 30, prac: 15, lab: 30 },
      "Базы данных": { credits: 5, lec: 30, prac: 0, lab: 45 },
    },
    certificates: [
      { page: 2, course_title: "Python для анализа данных", provider: "Coursera", hours: "40 ч", grade: "92%", date: "2025-03-14", verify_url: "" },
      { page: 3, course_title: "SQL для начинающих", provider: "Stepik", hours: "24 ч", grade: "", date: "2025-04-02", verify_url: "#" },
    ],
    mapping: { "0": 0 },
  };

  const STEPS = [
    {
      view: "upload",
      title: "Генератор экспертного заключения",
      text: "Генератор готовит экспертное заключение о перезачёте результатов неформального обучения: " +
        "из PDF с заявлением студента и сертификатами получается готовый DOCX.<br><br>" +
        "Порядок работы: <b>загрузить PDF → проверить данные → сгенерировать документ</b>.",
    },
    {
      view: "upload", target: "#dropzone",
      title: "Загрузите PDF",
      text: "Кликните по области или перетащите в неё файл. Нужен один PDF: " +
        "<b>первая страница — заявление</b> студента, <b>остальные — сертификаты</b>.",
    },
    {
      view: "upload", target: "#analyzeBtn",
      title: "Нажмите «Распознать»",
      text: "Кнопка станет активной после выбора файла, рядом появятся его имя и размер. " +
        "Распознавание через ИИ обычно занимает 30–90 секунд — не закрывайте вкладку.",
    },
    {
      view: "editor", target: "#step-editor .grid-2",
      title: "Проверьте данные студента",
      text: "ФИО, группа, образовательная программа и курс заполняются автоматически. " +
        "ОП подставляется по коду группы; если она не определилась — начните вводить название и выберите из списка.",
    },
    {
      view: "editor", target: ".cert-pool",
      title: "Нераспределённые сертификаты",
      text: "Здесь лежат сертификаты, которые система не смогла привязать к дисциплине. " +
        "«стр. N» — номер страницы в PDF. Название, организацию и часы можно исправить прямо в карточке, " +
        "«✓ Проверить» открывает проверку подлинности.",
    },
    {
      view: "editor", target: "#disciplineList .discipline",
      title: "Дисциплины из заявления",
      text: "Кредиты и часы подставляются из учебного плана — проверьте их. " +
        "Заполните <b>баллы</b> и <b>зачтённую оценку</b> (например, «92 (A-)»), при необходимости — соответствие и примечание. " +
        "«Удалить» убирает лишнюю дисциплину.",
    },
    {
      view: "editor", target: "#disciplineList .discipline-drop",
      title: "Привяжите сертификаты",
      text: "Перетащите карточку из левой панели в эту область или нажмите на карточке «→ дисциплина» и введите номер. " +
        "К одной дисциплине можно привязать несколько сертификатов. «Открепить» возвращает сертификат в панель.",
    },
    {
      view: "editor", target: "#addDisciplineBtn",
      title: "Не хватает дисциплины?",
      text: "Если ИИ пропустил дисциплину из заявления, добавьте её вручную и заполните поля.",
    },
    {
      view: "editor", target: "#generateBtn",
      title: "Сгенерируйте заключение",
      text: "«Сгенерировать DOCX» скачивает готовое экспертное заключение. " +
        "Если заявление открыто из «Экспертной очереди», рядом будут «Сохранить черновик» и «Утвердить + сохранить».",
    },
    {
      view: "editor",
      title: "Готово!",
      text: "Это были демо-данные — после закрытия туториала страница вернётся в прежнее состояние. " +
        "Открыть туториал снова можно кнопкой «Туториал» в шапке.",
    },
  ];

  let idx = 0;
  let target = null;
  let snap = null; // состояние страницы до начала тура
  let ui = null;

  function start() {
    if (snap) return;
    if (!$("step-loading").classList.contains("hidden")) {
      toast("Дождитесь окончания распознавания", "error");
      return;
    }
    snap = {
      scrollY: window.scrollY,
      hidden: SECTIONS.map(id => $(id).classList.contains("hidden")),
      fields: FIELDS.map(id => $(id).value),
      student: { ...state.student },
      disciplines: state.disciplines.map(d => ({ ...d })),
      certificates: state.certificates.map(c => ({ ...c })),
    };

    populateFromAnalyze(DEMO);
    Object.assign(state.disciplines[0], { grade_points: "92", final_grade: "92 (A-)" });
    render();

    ui = buildUi();
    document.querySelector(".topbar").inert = true;
    document.querySelector("main").inert = true;
    document.body.classList.add("tour-active");
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, { passive: true });
    show(0);
  }

  function end() {
    if (!snap) return;
    window.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", position);
    window.removeEventListener("scroll", position);
    ui.root.remove();
    document.querySelector(".topbar").inert = false;
    document.querySelector("main").inert = false;
    document.body.classList.remove("tour-active");

    state.student = snap.student;
    state.disciplines = snap.disciplines;
    state.certificates = snap.certificates;
    render();
    FIELDS.forEach((id, i) => { $(id).value = snap.fields[i]; });
    SECTIONS.forEach((id, i) => $(id).classList.toggle("hidden", snap.hidden[i]));
    window.scrollTo(0, snap.scrollY);

    snap = null;
    ui = null;
    target = null;
    $("tutorialBtn").focus();
  }

  function buildUi() {
    const root = document.createElement("div");
    root.innerHTML = `
      <div class="tour-backdrop"></div>
      <div class="tour-spot hidden"></div>
      <div class="tour-tip" role="dialog" aria-modal="true" aria-labelledby="tourTitle">
        <div class="tour-count"></div>
        <h3 class="tour-title" id="tourTitle"></h3>
        <div class="tour-text"></div>
        <div class="tour-actions">
          <button class="btn-ghost tour-skip" data-act="skip">Пропустить</button>
          <button class="btn-ghost" data-act="prev">← Назад</button>
          <button class="btn-primary" data-act="next">Далее →</button>
        </div>
      </div>
    `;
    const q = (sel) => root.querySelector(sel);
    q('[data-act="skip"]').addEventListener("click", end);
    q('[data-act="prev"]').addEventListener("click", () => show(idx - 1));
    q('[data-act="next"]').addEventListener("click", next);
    document.body.appendChild(root);
    return {
      root,
      backdrop: q(".tour-backdrop"),
      spot: q(".tour-spot"),
      tip: q(".tour-tip"),
      count: q(".tour-count"),
      title: q(".tour-title"),
      text: q(".tour-text"),
      prev: q('[data-act="prev"]'),
      next: q('[data-act="next"]'),
    };
  }

  function show(i) {
    idx = i;
    const s = STEPS[i];
    const editor = s.view === "editor";
    $("step-upload").classList.toggle("hidden", editor);
    $("step-loading").classList.add("hidden");
    $("step-editor").classList.toggle("hidden", !editor);

    ui.count.textContent = `Шаг ${i + 1} из ${STEPS.length}`;
    ui.title.textContent = s.title;
    ui.text.innerHTML = s.text;
    ui.prev.classList.toggle("hidden", i === 0);
    ui.next.textContent = i === STEPS.length - 1 ? "Готово" : "Далее →";

    target = s.target ? document.querySelector(s.target) : null;
    if (target) scrollToTarget(target);
    position();
    ui.next.focus();
  }

  function next() {
    if (idx < STEPS.length - 1) show(idx + 1);
    else end();
  }

  function onKey(e) {
    if (e.key === "Escape") end();
    else if (e.key === "ArrowRight") next();
    else if (e.key === "ArrowLeft" && idx > 0) show(idx - 1);
  }

  // Прокручиваем так, чтобы элемент и подсказка под ним поместились на экране
  function scrollToTarget(el) {
    const r = el.getBoundingClientRect();
    const block = r.height + GAP + ui.tip.offsetHeight;
    const free = window.innerHeight - TOPBAR;
    const offset = block + 2 * GAP < free ? TOPBAR + (free - block) / 2 : TOPBAR + GAP;
    window.scrollTo(0, window.scrollY + r.top - offset);
  }

  function position() {
    if (!ui) return;
    const t = target && target.isConnected ? target : null;
    const { spot, tip } = ui;
    const tw = tip.offsetWidth;
    const th = tip.offsetHeight;
    ui.backdrop.classList.toggle("dim", !t);
    spot.classList.toggle("hidden", !t);

    if (!t) {
      tip.style.left = `${(window.innerWidth - tw) / 2}px`;
      tip.style.top = `${Math.max(GAP, (window.innerHeight - th) / 2)}px`;
      return;
    }

    const r = t.getBoundingClientRect();
    spot.style.left = `${r.left - PAD}px`;
    spot.style.top = `${r.top - PAD}px`;
    spot.style.width = `${r.width + 2 * PAD}px`;
    spot.style.height = `${r.height + 2 * PAD}px`;

    let top;
    if (window.innerHeight - r.bottom >= th + PAD + 2 * GAP) top = r.bottom + PAD + GAP;
    else if (r.top >= th + PAD + 2 * GAP) top = r.top - PAD - GAP - th;
    else top = window.innerHeight - th - GAP;
    const left = Math.min(Math.max(GAP, r.left + r.width / 2 - tw / 2), window.innerWidth - tw - GAP);
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  }

  $("tutorialBtn").addEventListener("click", start);
})();
