# Деплой на постоянный ПК (Docker + CI/CD)

## Что создано в проекте

```
Dockerfile                    — образ Python-приложения
docker-compose.yml            — запуск app + ngrok контейнеров
.dockerignore                 — исключения из Docker-образа
.github/workflows/deploy.yml  — авто-деплой при push в main
```

После push в `main` → GitHub Actions автоматически пересобирает и перезапускает контейнеры на постоянном ПК.

---

## Шаг 1 — Добавить секреты на GitHub

`github.com → репозиторий → Settings → Secrets and variables → Actions → New repository secret`

| Name | Значение |
|------|----------|
| `GEMINI_API_KEY` | ключ Gemini API |
| `NGROK_AUTHTOKEN` | токен ngrok |
| `NGROK_DOMAIN` | домен ngrok (например `one-mutual-vulture.ngrok-free.app`) |

---

## Шаг 2 — Установить Docker Desktop на постоянном ПК

1. Скачать с [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)
2. При установке выбрать **"Use WSL 2 instead of Hyper-V"**
3. Перезагрузить ПК
4. Запустить Docker Desktop (иконка в трее не должна показывать ошибку)
5. Проверить в PowerShell:
   ```powershell
   docker --version
   ```

---

## Шаг 3 — Установить GitHub Actions Runner

> Небольшая программа, которая слушает GitHub и запускает деплой при каждом push.

**3.1** На GitHub: `Settings → Actions → Runners → New self-hosted runner`  
Выбрать: **Windows / x64**

Выполнить команды из открывшейся страницы в PowerShell **от администратора** (токен будет на той же странице):

```powershell
mkdir C:\actions-runner
cd C:\actions-runner

# Скачать — точная ссылка будет на странице GitHub
Invoke-WebRequest -Uri https://github.com/actions/runner/releases/download/v2.XX.X/actions-runner-win-x64-2.XX.X.zip -OutFile actions-runner.zip

# Распаковать
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory("$PWD\actions-runner.zip", "$PWD")

# Настроить (токен и URL — со страницы GitHub)
.\config.cmd --url https://github.com/ВАШ_ЛОГИН/ВАШ_РЕПОЗИТОРИЙ --token ТОКЕН
```

При настройке нажать Enter на всех вопросах (оставить по умолчанию).

**3.2** Установить как Windows-сервис (автозапуск при перезагрузке):

```powershell
.\svc.cmd install
.\svc.cmd start
```

Проверить:
```powershell
.\svc.cmd status   # должно быть "Running"
```

---

## Шаг 4 — Разрешить runner использовать Docker

Docker Desktop требует членства в группе `docker-users`. Добавить системного пользователя:

```powershell
Add-LocalGroupMember -Group "docker-users" -Member "NT AUTHORITY\SYSTEM"
```

Перезапустить сервис:
```powershell
.\svc.cmd stop
.\svc.cmd start
```

---

## Шаг 5 — Залить изменения в GitHub

На рабочем ПК (не на сервере):

```bash
git add .
git commit -m "Add Docker + CI/CD setup"
git push origin main
```

После push GitHub автоматически:
1. Запустит workflow на постоянном ПК
2. Создаст `.env` из секретов
3. Выполнит `docker compose up -d --build`

Прогресс и логи: `GitHub → Actions → Deploy`

---

## Как это работает

```
                  push в main
                      │
               GitHub Actions
                      │
          runner на постоянном ПК
                      │
         docker compose up --build
                      │
        ┌─────────────┴─────────────┐
        │                           │
   [app контейнер]          [ngrok контейнер]
   FastAPI :8765             публичный URL
        │                           │
        └──────── туннель ──────────┘
```

- **База данных и файлы** хранятся в именованном Docker volume — не теряются при деплое
- **Автоперезапуск** — `restart: always`, поднимется после перезагрузки ПК
- **Данные изолированы** от кода — `docker compose down` не удаляет volume

---

## Полезные команды на постоянном ПК

```bash
# Логи приложения в реальном времени
docker compose logs -f app

# Статус контейнеров
docker compose ps

# Перезапустить приложение
docker compose restart app

# Остановить всё
docker compose down

# Принудительный деплой без push (запустить вручную)
# GitHub → Actions → Deploy → Run workflow
```
