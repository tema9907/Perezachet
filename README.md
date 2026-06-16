# Перезачёт — система обработки заявлений

Веб-приложение для перезачёта дисциплин по сертификатам неформального обучения (СКУ им. М. Козыбаева). Студент подаёт заявление онлайн, эксперт получает его в очереди, проверяет распознанные данные и выгружает экспертное заключение в DOCX.

## Как это работает

```
Студент (/intake)
    │  заполняет форму: ФИО, группа, дисциплины, сертификаты
    ▼
/applications — список заявлений
    │  кнопка «Отправить на экспертизу»
    ▼
LLM-анализ PDF (фоновая задача)
    │  Gemini 2.5 Flash → OpenRouter (fallover)
    │  распознаёт сертификаты, сопоставляет с дисциплинами
    ▼
/approve — очередь заявлений для эксперта
    │  эксперт правит данные при необходимости
    │  нажимает «Утвердить»
    ▼
/conclusions — архив готовых заключений (скачать DOCX)
```

Дополнительно: ручная загрузка PDF на `/` минуя форму студента.

## Стек

- **Backend:** Python 3.11 + FastAPI + Uvicorn
- **PDF → изображения:** PyMuPDF
- **Vision LLM:** Google Gemini 2.5 Flash (основной) + OpenRouter (failover)
- **Генерация DOCX:** python-docx
- **Хранилище:** SQLite × 2 (очередь + заявления), файлы на диске
- **Frontend:** vanilla HTML/CSS/JS, SSE для real-time обновлений
- **Деплой:** Docker + ngrok + GitHub Actions (self-hosted runner)

## Страницы

| Путь | Назначение |
|---|---|
| `/` | Ручной анализ PDF: загрузить → распознать → редактировать → скачать DOCX |
| `/intake` | Форма заявления студента |
| `/applications` | Список поданных заявлений, отправка на экспертизу |
| `/approve` | Очередь заявлений для эксперта, утверждение |
| `/conclusions` | Архив готовых экспертных заключений, скачать DOCX |
| `/admin` | Административная панель (управление статусами, сброс) |

## Установка

```bash
python -m venv .venv

# Windows
.venv\Scripts\pip install -r requirements.txt

# Linux/Mac
.venv/bin/pip install -r requirements.txt
```

## Настройка `.env`

```dotenv
# LLM (хотя бы один обязателен)
GEMINI_API_KEY=AIza...
OPENROUTER_API_KEY=sk-or-v1-...

# Порядок провайдеров (по умолчанию: gemini первым)
PROVIDERS=gemini,openrouter

# Тонкая настройка (необязательно)
GEMINI_MODEL=gemini-2.5-flash
RENDER_DPI=150
ANALYZER_WORKERS=6
ANALYZER_RETRIES=3
```

**Получить ключи:**
- Gemini: `aistudio.google.com/apikey` → Create API key
- OpenRouter: `openrouter.ai/keys` → Create Key

Ключи можно также ввести прямо в UI на странице `/` — они сохраняются в `localStorage`.

## Запуск

```bash
# Windows
.venv\Scripts\python -m uvicorn app:app --port 8765

# Linux/Mac
.venv/bin/python -m uvicorn app:app --port 8765
```

Приложение доступно на `http://localhost:8765`.

## Запуск через Docker

```bash
# Собрать и запустить (app + ngrok туннель)
docker compose up -d --build

# Логи
docker compose logs -f app

# Остановить
docker compose down
```

Данные хранятся в именованном volume `nefrlearn_data` — не теряются при пересборке образа.

**Переменные для docker-compose:**

```dotenv
GEMINI_API_KEY=AIza...
NGROK_AUTHTOKEN=...
NGROK_DOMAIN=your-domain.ngrok-free.app
```

## CI/CD (авто-деплой)

При `git push origin main` GitHub Actions автоматически пересобирает и перезапускает контейнеры на постоянном ПК через self-hosted runner.

Подробная инструкция — в `DEPLOY.md`.

## CLI (без браузера)

```bash
# Один файл → DOCX в текущей папке
.venv/bin/python cli.py "Иванов.pdf"

# С указанием выходного файла
.venv/bin/python cli.py student.pdf -o report.docx

# Несколько PDF в папку
.venv/bin/python cli.py *.pdf -O ~/reports/

# Без авто-сопоставления дисциплин
.venv/bin/python cli.py student.pdf --no-mapping
```

## Структура проекта

```
├── app.py                   # FastAPI: все эндпоинты
├── analyzer.py              # PDF → vision LLM → JSON
├── doc_generator.py         # JSON → DOCX экспертного заключения
├── application_generator.py # данные формы → DOCX/PDF заявления
├── queue_store.py           # SQLite-очередь (.data/queue.sqlite3)
├── intake_store.py          # SQLite заявлений (.data/intake.sqlite3)
├── discipline_db.py         # база дисциплин и кредитов
├── discipline_db.json       # данные дисциплин
├── cert_verifier.py         # верификация сертификатов по URL
├── syslog.py                # логирование
├── cli.py                   # CLI для batch-обработки
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env                     # ключи (в .gitignore)
├── .data/                   # данные (в .gitignore)
│   ├── queue.sqlite3
│   ├── intake.sqlite3
│   ├── applications/        # PDF и DOCX заявлений студентов
│   └── conclusions/         # готовые DOCX экспертных заключений
└── static/
    ├── index.html / app.js        # ручной анализ PDF
    ├── intake.html / intake.js    # форма студента
    ├── applications.html / .js    # список заявлений
    ├── approve.html / approve.js  # очередь эксперта
    ├── conclusions.html / .js     # архив заключений
    └── admin.html / admin.js      # админ-панель
```

## API эндпоинты

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/health` | Статус: провайдеры, очередь |
| `POST` | `/api/analyze` | PDF → job_id (анализ в фоне) |
| `GET` | `/api/analyze/jobs/{job_id}` | Статус и результат задачи анализа |
| `POST` | `/api/generate` | JSON → DOCX (скачать) |
| `GET` | `/api/queue/stream` | SSE: real-time обновления очереди |
| `GET` | `/api/requests` | Список очереди |
| `GET` | `/api/requests/{id}` | Карточка заявления |
| `POST` | `/api/requests/{id}/edit` | Сохранить правки эксперта |
| `POST` | `/api/requests/{id}/approve` | Утвердить → сгенерировать DOCX |
| `POST` | `/api/requests/{id}/reanalyze` | Повторный LLM-анализ PDF |
| `DELETE` | `/api/requests/{id}` | Удалить из очереди |
| `GET` | `/api/requests/{id}/pdf` | Просмотреть исходный PDF |
| `POST` | `/api/intake/generate` | Данные формы + файлы сертификатов → DOCX заявления |
| `GET` | `/api/intake/applications` | Список заявлений студентов |
| `GET` | `/api/intake/applications/{id}` | Карточка заявления |
| `GET` | `/api/intake/applications/{id}/pdf` | Combined PDF (заявление + сертификаты) |
| `POST` | `/api/intake/applications/{id}/send-to-review` | Отправить на экспертизу |
| `GET` | `/api/applications/{id}/download` | Скачать DOCX заявления |
| `GET` | `/api/conclusions` | Список готовых заключений |
| `GET` | `/api/conclusions/{id}/download` | Скачать DOCX заключения |

## LLM-провайдеры

По умолчанию сначала пробуется Gemini, при ошибке — OpenRouter:

**Gemini:** `gemini-2.5-flash`

**OpenRouter (fallover, в порядке приоритета):**
```
google/gemma-4-26b-a4b-it:free
google/gemma-4-31b-it:free
nvidia/nemotron-nano-12b-v2-vl:free
baidu/qianfan-ocr-fast:free
```

## Статусы

**Заявления студентов** (`intake_store`):
- `created` — подано, не отправлено на экспертизу
- `in_review` — отправлено в очередь
- `done` — заключение готово

**Очередь эксперта** (`queue_store`):
- `analyzing` — LLM-анализ PDF в процессе
- `pending_approval` — ожидает проверки эксперта
- `approved` — утверждено (генерируется DOCX)
- `sent` — DOCX сохранён в `.data/conclusions/`
- `error` — ошибка на одном из этапов

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `GEMINI_API_KEY` | — | Ключ Google Gemini |
| `OPENROUTER_API_KEY` | — | Ключ OpenRouter |
| `PROVIDERS` | `gemini,openrouter` | Порядок попыток провайдеров |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Модель Gemini |
| `OPENROUTER_MODELS` | 4 модели | Список через запятую |
| `RENDER_DPI` | `150` | DPI рендера страниц PDF |
| `ANALYZER_WORKERS` | `6` | Параллельных запросов к LLM |
| `ANALYZER_RETRIES` | `3` | Повторных попыток при ошибке |
| `NGROK_AUTHTOKEN` | — | Токен ngrok (только Docker) |
| `NGROK_DOMAIN` | — | Домен ngrok (только Docker) |
