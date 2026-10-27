'use strict';

// ---- state ----
let PLAN = [];          // [{name, credits, ...}] — учебный план (опц., иначе тянет сервер)
let PLAN_COURSES = [];  // за какие курсы собран PLAN — показываем эксперту явно
let TRANSCRIPT = [];
let ROWS = [];
let FILE = null;
let APP_ID = null;
let SELECTS = {};

const $ = (id) => document.getElementById(id);

function toast(msg, isErr) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  t.style.background = isErr ? 'var(--danger)' : '';
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add('hidden'), isErr ? 7000 : 3500);
}

async function api(url, opts) {
  const r = await fetch(url, opts);
  let data = null;
  try { data = await r.json(); } catch (_) {}
  if (!r.ok) throw new Error((data && (data.detail || data.error)) || `HTTP ${r.status}`);
  return data;
}

function fillSelect(sel, options, { value, prepend } = {}) {
  sel.innerHTML = '';
  if (prepend) {
    const o = document.createElement('option');
    o.value = prepend.value; o.textContent = prepend.label;
    sel.appendChild(o);
  }
  for (const o of options) {
    const opt = document.createElement('option');
    opt.value = o.value; opt.textContent = o.label;
    sel.appendChild(opt);
  }
  if (value != null) sel.value = value;
}

// ================= selects =================
async function loadSelects(faculty) {
  $('selectsMeta').textContent = 'Загрузка справочников…';
  try {
    const d = await api('/api/formal/selects?faculty=' + encodeURIComponent(faculty || '58'));
    SELECTS = d;
    fillSelect($('selSpeciality'), (d.speciality || []).filter(o => o.value !== '0'));
    fillSelect($('selStream'), (d.stream || []).filter(o => o.value !== '0'),
      { prepend: { value: '', label: '— выберите поток —' }, value: '' });
    $('selectsMeta').textContent = `Специальностей: ${(d.speciality || []).length}`;
  } catch (e) {
    $('selectsMeta').textContent = '';
    toast('Справочники недоступны: ' + e.message + '. Можно вставить план вручную.', true);
    $('pasteBox').classList.remove('hidden');
  }
}

function streamMode() {
  const el = document.querySelector('input[name="streamMode"]:checked');
  return el ? el.value : 'auto';
}

// Годы обучения: 'auto' → только первый курс; иначе явный список курсов.
function selectedCourses() {
  const v = ($('selCourses') && $('selCourses').value) || 'auto';
  if (v === 'auto') return [1];
  return v.split(',').map(s => parseInt(s, 10)).filter(n => !isNaN(n));
}

function coursesLabel(courses) {
  const c = courses || selectedCourses();
  return c.length === 1 ? `${c[0]} курс` : `${c.join(', ')} курс`;
}

function currentTarget() {
  const specSel = $('selSpeciality');
  const specLabel = specSel.selectedOptions[0] ? specSel.selectedOptions[0].textContent : '';
  let stream_id = '', stream_label = '';
  if (streamMode() === 'manual') {
    const s = $('selStream');
    stream_id = s.value || '';
    stream_label = s.value ? (s.selectedOptions[0].textContent || '') : '';
  }
  return {
    faculty: '58',
    speciality: specSel.value,
    stream_id,               // задан → ручной режим (Stream=<id>); пусто → авто по году
    stream_label,
    courses: selectedCourses(),
    group: $('fGroup').value.trim(),
    program: normalizeProgram(specLabel),
  };
}

function normalizeProgram(label) {
  const m = (label || '').match(/^\s*([0-9][A-Z]\d{5,6})\s+(.+?)\s*$/);
  if (m) return `${m[1]} «${m[2]}»`;
  return (label || '').trim();
}

// ================= plan (preview / paste / append) =================
async function fetchPlan(courses, append) {
  const t = currentTarget();
  if (!t.speciality || t.speciality === '0') { toast('Выберите специальность', true); return; }
  const btn = append ? $('appendPlanBtn') : $('previewPlanBtn');
  const old = btn.textContent; btn.disabled = true; btn.textContent = 'Загрузка…';
  try {
    const d = await api('/api/formal/plan', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ faculty: t.faculty, speciality: t.speciality,
        stream_id: t.stream_id, stream_label: t.stream_label, courses, label: t.program }),
    });
    if (d.status === 'ok' && d.disciplines && d.disciplines.length) {
      if (append) {
        PLAN = PLAN.concat(d.disciplines);
        PLAN_COURSES = PLAN_COURSES.concat(courses);
        toast(`Добавлено (${coursesLabel(courses)}): ${d.disciplines.length} дисц.`);
      } else {
        PLAN = d.disciplines; PLAN_COURSES = courses.slice();
        toast(`План загружен, ${coursesLabel(courses)} (${d.source}): ${d.disciplines.length} дисц.`);
      }
      renderPlan(); $('pasteBox').classList.add('hidden');
    } else {
      toast(d.message || 'План не получен. Вставьте вручную.', true);
      $('pasteBox').classList.remove('hidden');
    }
  } catch (e) {
    toast('Ошибка: ' + e.message + '. Вставьте план вручную.', true);
    $('pasteBox').classList.remove('hidden');
  } finally { btn.disabled = false; btn.textContent = old; }
}

async function parsePaste() {
  const text = $('pasteText').value.trim();
  if (!text) { toast('Вставьте текст плана', true); return; }
  const btn = $('parsePasteBtn'); btn.disabled = true; btn.textContent = 'Распознаём…';
  try {
    const d = await api('/api/formal/plan', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pasted_text: text }),
    });
    PLAN = d.disciplines || [];
    PLAN_COURSES = [];   // вставленный вручную план к курсам сайта не привязан
    renderPlan();
    toast(`Распознано: ${PLAN.length} дисц.`);
  } catch (e) { toast('Ошибка: ' + e.message, true); }
  finally { btn.disabled = false; btn.textContent = 'Распознать вставленный план'; }
}

function renderPlan() {
  const box = $('planList'); box.innerHTML = '';
  PLAN.forEach((d, i) => {
    const row = document.createElement('div'); row.className = 'plan-row';
    const n = document.createElement('input'); n.value = d.name || '';
    n.oninput = () => { PLAN[i].name = n.value; };
    const c = document.createElement('input'); c.value = d.credits || ''; c.placeholder = 'кр.';
    c.oninput = () => { PLAN[i].credits = c.value; };
    const del = document.createElement('button'); del.className = 'row-del'; del.textContent = '×';
    del.onclick = () => { PLAN.splice(i, 1); renderPlan(); };
    row.append(n, c, del); box.appendChild(row);
  });
  $('planCount').textContent = PLAN.length;
  // явно показываем, за какие курсы собран план: иначе выбранное однажды
  // «1 и 2 курс» незаметно остаётся и план выглядит подозрительно большим
  const uniq = PLAN_COURSES.filter((c, i) => PLAN_COURSES.indexOf(c) === i).sort();
  const meta = $('planCourses');
  if (meta) {
    meta.innerHTML = uniq.length
      ? (uniq.length > 1 ? `<span class="nogr-mark">${coursesLabel(uniq)}</span>` : `· ${coursesLabel(uniq)}`)
      : '';
  }
  $('planBox').classList.remove('hidden');
}

function addPlanRow() { PLAN.push({ name: '', credits: '' }); renderPlan(); }

// ================= upload + process =================
function setupDropzone() {
  const dz = $('dropzone'), input = $('pdfInput');
  input.onchange = () => { if (input.files[0]) setFile(input.files[0]); };
  ['dragover', 'dragenter'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('drag'); }));
  ['dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('drag'); }));
  dz.addEventListener('drop', e => { const f = e.dataTransfer.files[0]; if (f) setFile(f); });
}

function setFile(f) {
  if (f.type !== 'application/pdf' && !f.name.toLowerCase().endsWith('.pdf')) { toast('Нужен PDF', true); return; }
  FILE = f;
  $('uploadMeta').textContent = `${f.name} (${(f.size / 1024).toFixed(0)} КБ)`;
  $('processBtn').disabled = false;
}

async function process() {
  if (!FILE) { toast('Загрузите PDF', true); return; }
  const t = currentTarget();
  if (!t.speciality || t.speciality === '0') { toast('Выберите специальность', true); return; }
  if (streamMode() === 'manual' && !t.stream_id) { toast('Выберите поток или переключитесь на «авто»', true); return; }
  const fd = new FormData();
  fd.append('file', FILE);
  fd.append('target', JSON.stringify(t));
  fd.append('plan', JSON.stringify({ disciplines: PLAN }));  // пусто = сервер тянет сам
  showLoading(true);
  try {
    const d = await api('/api/formal/analyze', { method: 'POST', body: fd });
    if (d.ok === false && d.need_paste) {
      showLoading(false);
      toast(d.message || 'Нужно вставить план вручную', true);
      $('pasteBox').classList.remove('hidden');
      $('pasteText').focus();
      return;
    }
    APP_ID = d.id;
    if (d.plan_source) {
      const st = d.stream ? `поток ${d.stream}, ` : '';
      toast(`План: ${d.plan_source} (${st}${coursesLabel(t.courses)}, ${d.plan_count} дисц.). ` +
        'Анализируем транскрипт…');
    }
    await pollApp(d.id);
  } catch (e) {
    showLoading(false);
    toast('Ошибка: ' + e.message, true);
  }
}

function showLoading(on) { $('step-loading').classList.toggle('hidden', !on); }

async function pollApp(id) {
  for (let i = 0; i < 120; i++) {
    await new Promise(r => setTimeout(r, 2000));
    let a;
    try { a = await api('/api/formal/applications/' + id); } catch (_) { continue; }
    if (a.status === 'pending_approval' || a.status === 'done') { showLoading(false); loadIntoEditor(a); loadList(); return; }
    if (a.status === 'error') { showLoading(false); toast('Ошибка: ' + (a.error || 'analysis failed'), true); return; }
  }
  showLoading(false); toast('Анализ занял слишком долго. Обновите список ниже.', true);
}

// ================= editor =================
function loadIntoEditor(a) {
  APP_ID = a.id;
  const edit = a.edit || {}, student = edit.student || {}, target = edit.target || {};
  const meta = edit.meta || a.meta || {};
  PLAN = (a.plan && a.plan.disciplines) || PLAN;
  TRANSCRIPT = (a.analyze && a.analyze.transcript) || [];
  ROWS = (edit.rows || []).map(normalizeRow);

  $('eName').value = student.name || a.student_name || '';
  $('eSrcInst').value = student.source_institution || '';
  $('eSrcProg').value = student.source_program || '';
  $('eProgram').value = target.program || a.target_program || '';
  $('eCourse').value = target.course || '1';
  $('mNum').value = meta.protocol_number || '';
  $('mDate').value = meta.protocol_date || '';
  $('mGroup').value = meta.group || target.group || a.target_group || '';
  $('mSem').value = meta.enroll_semester || '';
  $('mDiff').value = meta.academic_difference || '';

  renderWarnings((a.analyze && a.analyze.warnings) || []);
  renderTranscriptPool();
  renderRows();
  $('step-editor').classList.remove('hidden');
  $('downloads').classList.add('hidden');
  $('step-editor').scrollIntoView({ behavior: 'smooth' });
}

function renderWarnings(warnings) {
  const box = $('analyzeWarnings');
  if (!box) return;
  if (!warnings || !warnings.length) { box.classList.add('hidden'); box.innerHTML = ''; return; }
  box.classList.remove('hidden');
  box.style.cssText = 'background:#fef9c3;border:1px solid #f59e0b;border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:13px;color:#854d0e';
  box.innerHTML = '<b>⚠ Проверьте распознавание:</b><ul style="margin:6px 0 0 18px">' +
    warnings.map(w => `<li>${esc(w)}</li>`).join('') + '</ul>';
}

function renderTranscriptPool() {
  $('transcriptPool').innerHTML = TRANSCRIPT.map((t, i) => {
    const g = gradeStr(t);
    const h = (t.hours || '').toString().trim();
    return `${i + 1}. ${esc(t.name || '')} — ` +
      (h ? `${esc(h)} ч.` + (t.hours_derived ? ' <i>(из кредитов)</i>' : '')
         : '<span class="nogr-mark">объём не распознан</span>') + ', ' +
      (g ? esc(g) : '<span class="nogr-mark">оценка не распознана</span>');
  }).join('<br>') || '—';
  const missing = TRANSCRIPT.filter(t => !gradeStr(t)).length;
  $('poolMeta').innerHTML = TRANSCRIPT.length
    ? `— ${TRANSCRIPT.length} дисц.` +
      (missing ? `, <span class="nogr-mark">без оценки: ${missing}</span>` : '')
    : '';
}

function gradeStr(t) {
  const p = (t.grade_points || '').toString().trim(), l = (t.grade_letter || '').toString().trim();
  return p && l ? `${p}(${l})` : (p || l || '');
}

// Одной дисциплине плана может соответствовать НЕСКОЛЬКО предметов транскрипта.
// Источник истины — r.facts: [{name, credits, grade}]; плоские fact_* пересобираются
// из него (старые заявления, где были только плоские поля, поднимаются в facts).
// Объём факта — в ЧАСАХ (план СКУ в кредитах, транскрипты колледжей в часах).
const HOURS_PER_CREDIT = 15;

function num(v) { const m = String(v == null ? '' : v).match(/\d+(?:[.,]\d+)?/); return m ? parseFloat(m[0].replace(',', '.')) : null; }
function fmtNum(v) { return v == null ? '' : (Math.abs(v - Math.round(v)) < 0.05 ? String(Math.round(v)) : v.toFixed(1).replace('.', ',')); }

function normalizeRow(r) {
  const o = Object.assign({}, r);
  if (!Array.isArray(o.facts)) {
    const n = (o.fact_name || '').split('\n');
    const c = (o.fact_credits == null ? '' : String(o.fact_credits)).split('\n');
    const g = (o.fact_grade || '').split('\n');
    o.facts = n.map((name, i) => ({ name: name.trim(), hours: (c[i] || '').trim(), grade: (g[i] || '').trim() }))
      .filter(f => f.name);
  }
  // старые заявления хранили объём факта как credits — поднимаем в часы
  o.facts = o.facts.map(f => ({
    name: f.name || '',
    hours: fmtNum(num(f.hours != null ? f.hours : f.credits)),
    grade: f.grade || '',
  }));
  syncFacts(o);
  return o;
}

// Пересобирает плоские колонки и подсказывает зачтённую оценку по «весомому» предмету.
function syncFacts(r) {
  r.fact_name = r.facts.map(f => f.name).join('\n');
  r.fact_credits = r.facts.map(f => (f.hours ? f.hours + ' ч.' : '')).join('\n');
  r.fact_grade = r.facts.map(f => f.grade).join('\n');
  return r;
}

function suggestFinalGrade(r) {
  // «не соответствует» → дисциплина не зачтена и уходит в академразницу
  if (r.compliance === 'не соответствует') return 'АР';
  const graded = r.facts.filter(f => (f.grade || '').trim());
  if (!graded.length) return 'АР';
  const h = f => num(f.hours) || 0;
  return graded.reduce((a, b) => (h(b) > h(a) ? b : a)).grade;
}

// 1 кредит ≈ 15 ч.: сравниваем набранные часы с требуемыми по плану.
// В «Примечание» ничего не пишем — это поле эксперта.
function volumeCheck(r) {
  const credits = num(r.plan_credits);
  const required = credits == null ? null : credits * HOURS_PER_CREDIT;
  const got = r.facts.reduce((s, f) => s + (num(f.hours) || 0), 0);
  return { required, got, short: required != null && got > 0 && got < required };
}

// Объём меньше требуемого → «полное» понижаем до «частичного». Только понижаем:
// содержательную оценку даёт эксперт/модель, повышать её арифметикой нельзя.
function applyVolume(r) {
  const v = volumeCheck(r);
  if (r.compliance === 'полное' && v.short) r.compliance = 'частичное';
  return v;
}

function transcriptOptions() {
  // транскрипт техникума — до 100 дисциплин, а список нужен в каждой строке: мемоизируем
  if (transcriptOptions._src === TRANSCRIPT) return transcriptOptions._html;
  let opts = '<option value="">+ предмет из транскрипта…</option>';
  TRANSCRIPT.forEach((t, i) => {
    opts += `<option value="${i}">${esc(t.name || '').replace(/"/g, '')} (${gradeStr(t)})</option>`;
  });
  opts += '<option value="blank">+ пустая строка (вписать вручную)</option>';
  transcriptOptions._src = TRANSCRIPT;
  transcriptOptions._html = opts;
  return opts;
}

function complianceOptions(v) {
  return ['', 'полное', 'частичное', 'не соответствует'].map(o =>
    `<option value="${o}"${o === v ? ' selected' : ''}>${o || '—'}</option>`).join('');
}

// Предмет считаем «без оценки», если оценка не распозналась — её вписывают вручную.
function factNoGrade(f) { return !String(f.grade || '').trim(); }

// Дисциплина плана требует внимания, если хоть у одного её предмета нет оценки
// (или пуста итоговая зачтённая) — при этом сама дисциплина не в академразнице.
function rowNeedsGrade(r) {
  if (!r.facts.length) return false;               // это АР, у неё своя подсветка
  return r.facts.some(factNoGrade) || !String(r.final_grade || '').trim();
}

// Колонка «Фактически изучено»: по строке на каждый перезачитываемый предмет.
function factCol(r, field, extra) {
  if (!r.facts.length) return '<div class="fact-empty">—</div>';
  return r.facts.map((f, fi) => {
    const cls = (field === 'grade' && factNoGrade(f)) ? ' class="no-grade"' : '';
    const ph = field === 'grade' ? ' placeholder="нет оценки"' : '';
    return `<div class="fact-line"><input${cls}${ph} data-fi="${fi}" data-ff="${field}" ` +
      `value="${esc(f[field])}">` +
      (extra ? `<button class="fact-rm" data-rm="${fi}" title="Убрать предмет">×</button>` : '') +
      '</div>';
  }).join('');
}

function renderRows() {
  const body = $('resBody'); body.innerHTML = '';
  ROWS.forEach((r, i) => {
    const tr = document.createElement('tr');
    const isAr = !r.facts.length || (r.final_grade || '').toUpperCase() === 'АР';
    if (isAr) tr.className = 'ar';
    else if (rowNeedsGrade(r)) tr.className = 'nogr';
    const finalCls = (!isAr && !String(r.final_grade || '').trim()) ? ' class="no-grade"' : '';
    tr.innerHTML = `
      <td class="num">${i + 1}</td>
      <td><textarea data-f="plan_name" rows="1">${esc(r.plan_name)}</textarea></td>
      <td><input data-f="plan_credits" value="${esc(r.plan_credits)}"></td>
      <td>${factCol(r, 'name', false)}
        <select data-add class="fact-add">${transcriptOptions()}</select></td>
      <td>${factCol(r, 'hours', false)}</td>
      <td>${factCol(r, 'grade', true)}</td>
      <td><select data-f="compliance">${complianceOptions(r.compliance)}</select></td>
      <td><textarea data-f="note" rows="1">${esc(r.note)}</textarea></td>
      <td><input${finalCls} data-f="final_grade" value="${esc(r.final_grade)}"></td>
      <td><button class="row-del" title="Удалить">×</button></td>`;
    // подсветку снимаем/возвращаем сразу при вводе, без перерисовки строки
    const refreshWarn = () => {
      const row = ROWS[i];
      const ar = !row.facts.length || (row.final_grade || '').toUpperCase() === 'АР';
      tr.classList.toggle('ar', ar);
      tr.classList.toggle('nogr', !ar && rowNeedsGrade(row));
    };
    tr.querySelectorAll('[data-f]').forEach(el => {
      const ev = el.tagName === 'SELECT' ? 'change' : 'input';
      el.addEventListener(ev, () => {
        ROWS[i][el.dataset.f] = el.value;
        // сняли/поставили «не соответствует» — пересчитываем зачтённую оценку
        if (el.dataset.f === 'compliance') { ROWS[i].final_grade = suggestFinalGrade(ROWS[i]); renderRows(); return; }
        if (el.dataset.f === 'final_grade') {
          const ar = (el.value || '').toUpperCase() === 'АР';
          el.classList.toggle('no-grade', !ar && ROWS[i].facts.length > 0 && !el.value.trim());
          refreshWarn();
        }
        if (el.dataset.f === 'plan_credits') autoDiff();
      });
    });
    // правка предмета на месте — без перерисовки, чтобы не терять фокус
    tr.querySelectorAll('[data-ff]').forEach(el => {
      el.addEventListener('input', () => {
        r.facts[parseInt(el.dataset.fi, 10)][el.dataset.ff] = el.value;
        syncFacts(r);
        if (el.dataset.ff === 'grade') {
          el.classList.toggle('no-grade', !el.value.trim());
          refreshWarn();
        }
      });
    });
    tr.querySelectorAll('[data-rm]').forEach(el => {
      el.addEventListener('click', () => { removeFact(i, parseInt(el.dataset.rm, 10)); });
    });
    tr.querySelector('[data-add]').addEventListener('change', (e) => addFact(i, e.target.value));
    tr.querySelector('.row-del').addEventListener('click', () => { ROWS.splice(i, 1); renderRows(); });
    body.appendChild(tr);
  });
  const need = ROWS.filter(rowNeedsGrade).length;
  $('rowsMeta').innerHTML = need
    ? `<span class="nogr-mark">без оценки: ${need}</span> — впишите вручную`
    : '';
  autoDiff();
}

function addFact(i, val) {
  const r = ROWS[i];
  if (val === 'blank') r.facts.push({ name: '', hours: '', grade: '' });
  else {
    const t = TRANSCRIPT[parseInt(val, 10)];
    if (!t) { renderRows(); return; }
    r.facts.push({ name: t.name || '', hours: (t.hours || '').toString(), grade: gradeStr(t) });
  }
  syncFacts(r);
  r.compliance = r.compliance || 'полное';
  r.final_grade = suggestFinalGrade(r);
  applyVolume(r);
  renderRows();
}

function removeFact(i, fi) {
  const r = ROWS[i];
  r.facts.splice(fi, 1);
  syncFacts(r);
  if (!r.facts.length) { r.compliance = ''; r.final_grade = 'АР'; }
  else { r.final_grade = suggestFinalGrade(r); applyVolume(r); }
  renderRows();
}

function addRow() {
  ROWS.push(normalizeRow({ plan_name: '', plan_credits: '', facts: [], compliance: '', note: '', final_grade: 'АР' }));
  renderRows();
}

function autoDiff() {
  if ($('mDiff').value.trim()) return;
  let sum = 0;
  ROWS.forEach(r => {
    if (!(r.facts || []).length || (r.final_grade || '').toUpperCase() === 'АР') {
      const c = parseInt(r.plan_credits, 10); if (!isNaN(c)) sum += c;
    }
  });
  $('mDiff').placeholder = 'авто: ' + sum;
}

function collectEdit() {
  return {
    student: { name: $('eName').value, source_institution: $('eSrcInst').value, source_program: $('eSrcProg').value },
    target: { program: $('eProgram').value, course: $('eCourse').value, group: $('mGroup').value },
    rows: ROWS,
    meta: { protocol_number: $('mNum').value, protocol_date: $('mDate').value, group: $('mGroup').value,
      enroll_semester: $('mSem').value, academic_difference: $('mDiff').value },
  };
}

async function saveEdit(silent) {
  if (!APP_ID) return;
  await api('/api/formal/applications/' + APP_ID + '/edit', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(collectEdit()),
  });
  if (!silent) toast('Сохранено');
}

async function generate() {
  if (!APP_ID) return;
  const btn = $('genBtn'); btn.disabled = true; btn.textContent = 'Генерация…';
  try {
    await saveEdit(true);
    await api('/api/formal/applications/' + APP_ID + '/generate', { method: 'POST' });
    const dl = $('downloads'); dl.classList.remove('hidden');
    dl.innerHTML = `<span class="tag ok">Готово</span>
      <a class="btn-primary" href="/api/formal/applications/${APP_ID}/conclusion">⬇ Заключение</a>
      <a class="btn-primary" href="/api/formal/applications/${APP_ID}/protocol">⬇ Протокол</a>`;
    toast('Документы сгенерированы'); loadList();
  } catch (e) { toast('Ошибка генерации: ' + e.message, true); }
  finally { btn.disabled = false; btn.textContent = 'Сгенерировать документы'; }
}

function esc(s) { return (s == null ? '' : String(s)).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

// ================= list =================
async function loadList() {
  try {
    const d = await api('/api/formal/applications');
    const box = $('flist');
    if (!d.items.length) { box.innerHTML = '<p class="subtle">Пока нет заявлений.</p>'; return; }
    box.innerHTML = '';
    d.items.forEach(a => {
      const el = document.createElement('div'); el.className = 'flist-item';
      const st = { analyzing: 'wait', pending_approval: 'wait', done: 'ok', error: 'ar', created: 'wait' }[a.status] || 'wait';
      const stLabel = { analyzing: 'анализ…', pending_approval: 'на проверке', done: 'готово', error: 'ошибка', created: 'черновик' }[a.status] || a.status;
      el.innerHTML = `<div><strong>${esc(a.student_name) || '(без имени)'}</strong>
        <div class="subtle">${esc(a.target_program || '')} • ${esc(a.source_program || '')}</div></div>
        <div class="inline-actions"><span class="tag ${st}">${stLabel}</span>
        <button class="row-del" data-del="${a.id}" title="Удалить">×</button></div>`;
      el.onclick = (e) => { if (e.target.dataset.del) { delApp(a.id); e.stopPropagation(); return; } openApp(a.id); };
      box.appendChild(el);
    });
  } catch (e) { $('flist').innerHTML = '<p class="subtle">Ошибка загрузки списка.</p>'; }
}

async function openApp(id) {
  try {
    const a = await api('/api/formal/applications/' + id);
    if (a.status === 'analyzing') { toast('Ещё анализируется…'); return; }
    loadIntoEditor(a);
  } catch (e) { toast('Ошибка: ' + e.message, true); }
}

async function delApp(id) {
  if (!confirm('Удалить заявление?')) return;
  try { await api('/api/formal/applications/' + id, { method: 'DELETE' }); loadList(); toast('Удалено'); }
  catch (e) { toast('Ошибка: ' + e.message, true); }
}

// ================= init =================
window.addEventListener('DOMContentLoaded', () => {
  const yy = String((new Date().getFullYear() - 1) % 100).padStart(2, '0');
  const hint = $('autoStreamHint'); if (hint) hint.textContent = `-${yy}`;
  document.querySelectorAll('input[name="streamMode"]').forEach(el =>
    el.addEventListener('change', () => $('selStream').classList.toggle('hidden', streamMode() !== 'manual')));
  loadSelects('58');
  loadList();
  setupDropzone();
  $('processBtn').onclick = process;
  $('previewPlanBtn').onclick = () => fetchPlan(selectedCourses(), false);
  $('appendPlanBtn').onclick = () => fetchPlan([parseInt($('appendCourse').value, 10)], true);
  $('refreshSelectsBtn').onclick = () => loadSelects('58');
  $('parsePasteBtn').onclick = parsePaste;
  $('addPlanBtn').onclick = addPlanRow;
  $('addRowBtn').onclick = addRow;
  $('saveBtn').onclick = () => saveEdit(false);
  $('genBtn').onclick = generate;
  $('backBtn').onclick = () => $('step-editor').classList.add('hidden');
  $('reloadListBtn').onclick = loadList;
});
