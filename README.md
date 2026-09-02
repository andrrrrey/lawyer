# Lawyer — AI-система контроля лидов и маркетинговой аналитики

Система автоматизированного контроля обработки лидов и сделок по регламенту
заказчика и сквозной маркетинговой аналитики (два Bitrix24, три аккаунта
Яндекс Директ/Метрики и фактические поступления 1С:УНФ). Разрабатывается по ТЗ.
Утверждённый визуальный
эталон — `lawyer_prototype.html` (изменению не подлежит).

> **Статус:** Этап A завершён — каркас, инфраструктура, аутентификация.
> Наполнение разделов данными и логикой — на Этапах B–E (см. дорожную карту).

## Технологический стек

- **Фронтенд:** React 18 + TypeScript, Vite, Ant Design 5, ECharts, TanStack Query, React Router
- **Бэкенд:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic
- **БД:** PostgreSQL 16
- **Планировщик:** APScheduler (worker)
- **Веб-сервер:** nginx (реверс-прокси; TLS/Let's Encrypt — на Этапе E)
- **Инфраструктура:** Docker + Docker Compose

## Структура

```
lawyer/
├── docker-compose.yml         # db · api · worker · web(nginx)
├── docker-compose.dev.yml     # оверрайд для разработки (порты, hot-reload)
├── .env.example               # шаблон переменных окружения
├── backend/                   # FastAPI, БД, интеграции, планировщик, тесты
└── frontend/                  # React + AntD (оболочка и разделы из прототипа)
```

## Быстрый старт (Docker)

```bash
# 1. Подготовить окружение
cp .env.example .env
#    отредактируйте .env: задайте ADMIN_LOGIN, ADMIN_PASSWORD,
#    сгенерируйте SESSION_SECRET:  openssl rand -hex 32

# 2. Собрать и запустить
docker compose up --build

# 3. Открыть в браузере
#    http://localhost  → страница входа → логин/пароль из .env
```

Сервисы: `db` (PostgreSQL), `api` (FastAPI), `worker` (планировщик),
`web` (nginx: собранный фронтенд + прокси `/api`).

## Развёртывание на VPS (production, HTTPS)

Полная пошаговая инструкция для домена **lawyer.futuguru.com** —
**[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**. Кратко:

```bash
cp .env.example .env && nano .env         # домен, пароли, ключи API
./scripts/init-letsencrypt.sh             # выпуск TLS-сертификата Let's Encrypt
docker compose -f docker-compose.prod.yml up -d --build
```

Куда вносить каждый API-ключ — **[docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)**.

## Режим разработки

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
#   API с автоперезагрузкой + Swagger:  http://localhost:8000/api/docs
#   PostgreSQL:                         localhost:5432
```

Локальный фронтенд без Docker (проксирует `/api` на `localhost:8000`):

```bash
cd frontend && npm install && npm run dev   # http://localhost:5173
```

## Тесты и проверки

```bash
# Backend
cd backend && pip install -e ".[dev]" && ruff check app tests && pytest -q

# Frontend
cd frontend && npm install && npm run build
```

## Переменные окружения

Все секреты и параметры — в `.env` (см. `.env.example`, в репозиторий не
коммитится). Ключевое:

- `DATA_SOURCE=mock|real` — источник данных: демо-данные прототипа (по
  умолчанию, для разработки) или боевые интеграции (Этап E).
- `ADMIN_LOGIN` / `ADMIN_PASSWORD` — единый вход в дашборд и админ-панель.
- `SESSION_SECRET` — подпись сессионных токенов.
- Доступы к интеграциям (два Bitrix24, три связки Директ/Метрика, 1С:УНФ) и
  LLM — заполняются на Этапе E, когда заказчик выдаст доступы.

## Дорожная карта (соответствует разделу 10 ТЗ)

| Этап | Содержание | Статус |
|------|------------|--------|
| A | Каркас, Docker, аутентификация, 6 разделов-заготовок | ✅ готово |
| B | Модели БД, адаптеры интеграций + мок-данные, API | ✅ готово |
| C | Мониторинг Битрикс24, движок регламента, админ-панель | ✅ готово |
| D | Сквозная аналитика, ROMI, AI-слой, наполнение дашборда | ✅ готово |
| E | Боевые интеграции, TLS/домен, развёртывание, приёмка | ✅ готово |

## Документация

- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — развёртывание на VPS (домен, HTTPS)
- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) — API-ключи: где взять и куда вносить
- [docs/ADMIN.md](docs/ADMIN.md) — эксплуатация (бэкапы, логи, обновление)
- [docs/ROMI_METHODOLOGY.md](docs/ROMI_METHODOLOGY.md) — методика ROMI/маржи/НДС
- [docs/DB_SCHEMA.md](docs/DB_SCHEMA.md) — схема базы данных
- [docs/ACCEPTANCE_CHECKLIST.md](docs/ACCEPTANCE_CHECKLIST.md) — чек-лист приёмки
