# Развёртывание на сервере ВУЗа (Linux/Windows)

Проект: локальная CRM/SRM‑система сервисного центра ремонта техники.  
Стек: Python 3.10+, FastAPI, Jinja2, SQLite.

В проекте по умолчанию используется SQLite, поэтому для запуска не нужен отдельный сервер БД.

---

## 1) Требования к серверу

- Linux (Ubuntu/Debian) или Windows Server
- Python **3.10+**
- Доступ к портам `8000` (или к `80/443`, если используется Nginx)
- Доступ на запись в директории проекта (папки `data/`, `uploads/`, `outputs/`)

---

## 2) Клонирование репозитория

```bash
git clone <ваш_репозиторий.git>
cd <папка_проекта>
```

---

## 3) Создание окружения и установка зависимостей

### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## 4) Настройка `.env`

Скопируйте пример и отредактируйте:

```bash
cp .env.example .env
```

Ключевые параметры:

- `APP_ENV=production`
- `HOST=0.0.0.0`
- `PORT=8000`
- `SECRET_KEY=change_me` (обязательно поменять)
- `DATABASE_URL=sqlite:///./data/srm.db`
- `UPLOADS_DIR=./uploads`
- `ARTIFACTS_DIR=./outputs`
- `LOG_DIR=./outputs/logs`
- `DEBUG=false` (**в production запрещено DEBUG=true**)

Важно: после первого входа на сервере необходимо сменить пароли учётных записей.

---

## 5) Подготовка папок

```bash
mkdir -p data uploads outputs outputs/logs
```

---

## 6) Запуск приложения

### Вариант A — напрямую через uvicorn

```bash
uvicorn srm.api.app:app --host 0.0.0.0 --port 8000
```

### Вариант B — скриптом

Linux:
```bash
bash scripts/run_server.sh
```

Windows:
```powershell
.\scripts\run_server.ps1
```

---

## 7) Проверка работоспособности

- Healthcheck:
  - `GET /health` → `{"status":"ok"}`
  - `GET /ready` → проверка БД/папок/активных правил

Проверка из CLI:
```bash
python -m srm.cli check-deploy
```

---

## 8) Демо‑пользователи

В локальном режиме создаются автоматически:
- `admin / admin123`
- `manager / manager123`
- `master / master123`
- `analyst / analyst123`

В production (`APP_ENV=production`) демо‑пользователи **создаются только если БД пустая**.

---

## 9) systemd (Linux) — пример

Файл: `deploy/srm.service`

Быстрый старт:
```bash
sudo cp deploy/srm.service /etc/systemd/system/srm.service
sudo systemctl daemon-reload
sudo systemctl enable --now srm
sudo systemctl status srm
```

Перед этим отредактируйте:
- `WorkingDirectory`
- `ExecStart`
- `EnvironmentFile`
- пользователя `User/Group`

---

## 10) Nginx (Linux) — пример

Файл: `deploy/nginx_srm.conf`

Скопируйте конфиг в Nginx и перезапустите:
```bash
sudo cp deploy/nginx_srm.conf /etc/nginx/sites-available/srm.conf
sudo ln -sf /etc/nginx/sites-available/srm.conf /etc/nginx/sites-enabled/srm.conf
sudo nginx -t
sudo systemctl reload nginx
```

---

## 11) Типовые ошибки и решения

- **`DEBUG=true запрещён в APP_ENV=production`**
  - Установите `DEBUG=false` в `.env`.

- **`sqlite3.OperationalError: unable to open database file`**
  - Проверьте путь `DATABASE_URL`/`SRM_DB_PATH`.
  - Проверьте права на папку `data/` и наличие директории.

- **Не пишутся файлы в `uploads/` или `outputs/`**
  - Проверьте права на запись и параметры `UPLOADS_DIR`/`ARTIFACTS_DIR`.

