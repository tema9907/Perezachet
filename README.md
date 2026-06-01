# Экспертное заключение — генератор

Веб-приложение для автоматического заполнения «Экспертного заключения» по результатам неформального обучения. На входе — PDF с заявлением студента и сертификатами курсов, на выходе — `.docx` с готовой таблицей.

## Как это работает

```
┌──────────────┐   ┌──────────────────┐   ┌──────────────────────┐   ┌──────────────┐
│  PDF файл    │──▶│ PyMuPDF: страница│──▶│ Vision LLM           │──▶│ Редактор UI  │
│ (заявление + │   │   → PNG (150 DPI)│   │ OpenRouter (4 модели)│   │ или очередь→ │
│  сертификаты)│   └──────────────────┘   │ ↓ failover           │   │ docx         │
└──────────────┘                          │ Gemini (резерв)      │   └──────────────┘
                                          └──────────────────────┘
```

- **Заявление (стр. 1)** — рукописное, vision-модель распознаёт ФИО, группу, курс, телефон, список дисциплин и дату.
- **Сертификаты (стр. 2+)** — даже если повернуты на 90°, модель извлекает название курса, провайдера, часы, оценку и дату.
- **Cross-validation** — ФИО из сертификатов используется для коррекции рукописного из заявления.
- **Авто-сопоставление** — LLM подсказывает, какой сертификат к какой дисциплине относится.
- **Failover** — если OpenRouter упёрся в дневной лимит модели, пробуется следующая (4 модели подряд), затем Gemini.

## Стек

- **Backend:** Python 3 + FastAPI + Uvicorn
- **PDF → картинки:** PyMuPDF
- **Vision-провайдеры:** OpenRouter (несколько `:free` моделей) + Google Gemini как резерв
- **Генерация DOCX:** python-docx
- **Google Drive:** google-api-python-client (service account + OAuth)
- **Очередь:** SQLite (`queue_store.py`)
- **Frontend:** vanilla HTML/CSS/JS

## Установка

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows
# .venv/bin/pip install -r requirements.txt     # Linux/Mac
```

## Настройка ключей

### LLM-провайдеры (обязательно хотя бы один)

**OpenRouter** — даёт доступ к 4 бесплатным vision-моделям с авто-фейловером:
1. Зайти на https://openrouter.ai/keys (вход через Google/GitHub)
2. **«Create Key»** → скопировать `sk-or-v1-...`

**Gemini** (резерв):
1. https://aistudio.google.com/apikey → **«Create API key»**
2. Скопировать `AIza...`

### Google Drive (опционально)

Для автоматического опроса папки входящих PDF и загрузки готовых DOCX.

**Service account (для чтения PDF):**
1. Google Cloud Console → IAM → Сервисные аккаунты → создать
2. Выдать роль «Редактор» на входную папку Drive
3. Скачать JSON ключ → сохранить в `secrets/`

**OAuth (для загрузки DOCX в «Мой диск»):**
```bash
python drive_oauth_setup.py   # открывает браузер, сохраняет токен
```

### Файл `.env`

```dotenv
OPENROUTER_API_KEY=sk-or-v1-...
GEMINI_API_KEY=AIza...                    # необязательно

# Google Drive (необязательно)
DRIVE_ENABLED=true
DRIVE_SERVICE_ACCOUNT_JSON=secrets/sa.json
DRIVE_INPUT_FOLDER_ID=<ID входной папки>
DRIVE_OUTPUT_FOLDER_ID=<ID выходной папки>
DRIVE_INTAKE_FOLDER_ID=<ID папки заявлений студентов>
DRIVE_POLL_INTERVAL=60                    # секунды между опросами
DRIVE_UPLOAD_AUTH=service_account         # или oauth
```

API-ключи LLM можно также ввести прямо в UI — они сохраняются в `localStorage` браузера.

## Запуск

```bash
.venv/Scripts/python -m uvicorn app:app --port 8765   # Windows
# .venv/bin/python -m uvicorn app:app --port 8765     # Linux/Mac
```

## Страницы и workflow

### `/` — Ручной анализ PDF

1. Перетащить PDF в дропзону → «Распознать» (30–90 с)
2. Проверить ФИО, группу, код ОП, курс
3. Перетащить сертификаты в нужные дисциплины (drag-and-drop)
4. Задать кредиты, часы, баллы, соответствие, итоговую оценку
5. «Сгенерировать DOCX» → скачивается `ЭЗ_<ФИО>.docx`

### `/intake` — Форма заявления (для студентов)

Студент заполняет заявление онлайн: ФИО, группа, факультет, список дисциплин и сертификаты. Результат:
- Скачивается `Заявление_<ФИО>.docx` для подписи
- Объединённый PDF (заявление + сертификаты) автоматически загружается в Drive-папку заявлений (`DRIVE_INTAKE_FOLDER_ID`)

### `/approve` — Очередь и утверждение (для экспертов)

Если включён Drive-воркер (`DRIVE_ENABLED=true`), приложение само опрашивает входную папку. При появлении нового PDF:
1. Автоматически распознаёт и добавляет в очередь (статус `pending_approval`)
2. Эксперт открывает `/approve`, редактирует результаты при необходимости
3. Нажимает «Утвердить» → DOCX генерируется и загружается в выходную папку Drive (статус `sent`)

Статусы очереди: `pending_approval` → `approved` → `sent` / `error`

## CLI (без браузера)

```bash
# один файл → ЭЗ_<имя>.docx в текущей папке
.venv/bin/python cli.py "Сычёв В.А.pdf"

# с явным именем выходного файла
.venv/bin/python cli.py student.pdf -o report.docx

# несколько PDF разом в указанную папку
.venv/bin/python cli.py *.pdf -O ~/reports/

# без LLM-сопоставления (экономит запросы)
.venv/bin/python cli.py student.pdf --no-mapping

# сохранить распознанные данные в .json для отладки
.venv/bin/python cli.py student.pdf --json
```

## Структура проекта

```
NefrLearn/
├── app.py                   # FastAPI: все эндпоинты + Drive-воркер
├── analyzer.py              # PDF → vision-провайдеры → JSON
├── doc_generator.py         # python-docx → таблица экспертного заключения
├── application_generator.py # python-docx/PDF → бланк заявления студента
├── drive_client.py          # Google Drive API (SA + OAuth): read/upload
├── drive_oauth.py           # OAuth credentials helpers
├── drive_oauth_setup.py     # Одноразовая авторизация OAuth через браузер
├── queue_store.py           # SQLite-очередь заявлений
├── discipline_db.py         # База дисциплин: кредиты, часы, сопоставление
├── discipline_db.json       # Данные дисциплин
├── cert_verifier.py         # Верификация сертификатов по URL провайдеров
├── syslog.py                # Логирование
├── cli.py                   # CLI для batch-обработки
├── run.sh                   # Однострочный запуск
├── requirements.txt
├── .env                     # API ключи и Drive-конфиг (в .gitignore)
├── secrets/                 # JSON ключи SA и OAuth-токен (в .gitignore)
├── .data/queue.sqlite3      # SQLite файл очереди (создаётся автоматически)
└── static/
    ├── index.html           # Ручной анализ PDF
    ├── approve.html         # Очередь и утверждение
    ├── intake.html          # Форма заявления студента
    ├── app.js
    └── style.css
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Ключ OpenRouter (рекомендуется) |
| `GEMINI_API_KEY` | — | Ключ Gemini (резерв) |
| `PROVIDERS` | `openrouter,gemini` | Порядок попыток провайдеров |
| `OPENROUTER_MODELS` | 4 модели | Список моделей OpenRouter через запятую |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Модель Gemini |
| `RENDER_DPI` | `150` | DPI рендера страниц PDF |
| `ANALYZER_WORKERS` | `2` | Параллельных запросов к API |
| `ANALYZER_RETRIES` | `2` | Повторных попыток при transient ошибках |
| `DRIVE_ENABLED` | — | `true` для включения Drive-воркера |
| `DRIVE_SERVICE_ACCOUNT_JSON` | — | Путь к JSON ключу сервисного аккаунта |
| `DRIVE_INPUT_FOLDER_ID` | — | ID Drive-папки с входящими PDF |
| `DRIVE_OUTPUT_FOLDER_ID` | — | ID Drive-папки для выходных DOCX |
| `DRIVE_INTAKE_FOLDER_ID` | — | ID Drive-папки для заявлений из `/intake` |
| `DRIVE_POLL_INTERVAL` | `60` | Интервал опроса входной папки (секунды) |
| `DRIVE_UPLOAD_AUTH` | `service_account` | Режим загрузки: `service_account` или `oauth` |
| `DRIVE_OAUTH_TOKEN_JSON` | `secrets/drive-oauth-token.json` | Путь к OAuth-токену |

**Дефолтный список моделей OpenRouter:**
```
google/gemini-2.0-flash-exp:free
qwen/qwen-2.5-vl-72b-instruct:free
meta-llama/llama-3.2-90b-vision-instruct:free
mistralai/pixtral-12b:free
```

## API эндпоинты

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/` | Ручной анализ PDF |
| `GET` | `/intake` | Форма заявления студента |
| `GET` | `/approve` | Очередь и утверждение |
| `GET` | `/api/health` | Статус: провайдеры, Drive, очередь |
| `POST` | `/api/analyze` | PDF → JSON (multipart: `pdf`, `gemini_api_key`, `openrouter_api_key`, `auto_map`) |
| `POST` | `/api/generate` | JSON → DOCX (экспертное заключение) |
| `POST` | `/api/intake/generate` | Данные формы + файлы → DOCX заявления + PDF в Drive |
| `GET` | `/api/requests` | Список очереди |
| `GET` | `/api/requests/{id}` | Карточка заявления |
| `POST` | `/api/requests/{id}/edit` | Сохранить черновик редактирования |
| `POST` | `/api/requests/{id}/approve` | Утвердить → сгенерировать DOCX → загрузить в Drive |
| `POST` | `/api/requests/{id}/reanalyze` | Повторно распознать PDF с Drive |

## Примечания

- Таблица в DOCX: 12 колонок, A4 landscape, Times New Roman 12pt — совместима с Word 2007+.
- Если префикс группы не в `PROGRAM_MAP` (`doc_generator.py`), код ОП можно ввести вручную.
- Сервисный аккаунт не имеет квоты Google Drive — для загрузки DOCX в «Мой диск» используйте `DRIVE_UPLOAD_AUTH=oauth`.
- `.env` и `secrets/` в `.gitignore` — ключи в репозиторий не утекут.
