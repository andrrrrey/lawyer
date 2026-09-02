# Развёртывание Lawyer на VPS (домен lawyer.futuguru.com)

Пошаговая инструкция запуска системы на сервере с HTTPS. Занимает ~20–30 минут.

## 0. Что потребуется
- VPS: Ubuntu 22.04/24.04 LTS, 2–4 vCPU, 8 ГБ RAM, 60–80 ГБ SSD, root/SSH-доступ.
- Домен **lawyer.futuguru.com** с доступом к DNS-настройкам.
- Ключи API интеграций — см. [INTEGRATIONS.md](INTEGRATIONS.md) (можно заполнить позже: система стартует на демо-данных).

## 1. DNS: направить домен на сервер
В панели управления доменом futuguru.com создайте **A-запись**:

```
lawyer.futuguru.com.   A   <IP_вашего_VPS>
```

Проверьте распространение (с локальной машины):
```bash
dig +short lawyer.futuguru.com   # должен вернуть IP вашего VPS
```
TLS-сертификат не выпустится, пока запись не указывает на сервер.

## 2. Подготовка сервера
Подключитесь по SSH и установите Docker:
```bash
ssh root@<IP_вашего_VPS>

# Docker + Compose plugin
curl -fsSL https://get.docker.com | sh
docker compose version   # проверка

# Открыть порты (если включён firewall)
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
```

## 3. Получить код
```bash
git clone https://github.com/andrrrrey/lawyer.git /opt/lawyer
cd /opt/lawyer
git checkout main
```

## 4. Настроить окружение (.env)
```bash
cp .env.example .env
nano .env
```
Заполните минимум:
- `DOMAIN=lawyer.futuguru.com`, `PUBLIC_URL=https://lawyer.futuguru.com`
- `LETSENCRYPT_EMAIL=<ваш e-mail>`
- `POSTGRES_PASSWORD`, `ADMIN_LOGIN`, `ADMIN_PASSWORD` — задайте надёжные значения
- `SESSION_SECRET` — сгенерируйте: `openssl rand -hex 32`
- `DATA_SOURCE=mock` (пока нет доступов) либо `real` (когда заполните интеграции)

Куда вносить ключи API каждой интеграции — подробно в [INTEGRATIONS.md](INTEGRATIONS.md).
Все секреты хранятся только в `.env` (в репозиторий не попадают).

## 5. Запуск: быстрый путь (рекомендуется) или сборка на сервере

Два способа. **Быстрый** скачивает готовые образы из GitHub Container Registry
(собираются автоматически в GitHub Actions при пуше) — на VPS ничего не
компилируется, разворачивание ~1–2 минуты. **Сборка на сервере** компилирует
образы локально: на слабом VPS это 15–30 минут.

### Вариант A — готовые образы из реестра (быстро) ⭐
Предпосылки: workflow `.github/workflows/docker-images.yml` собрал образы (вкладка
**Actions** в GitHub — зелёная галочка). Сделайте образы в GHCR **публичными**
(Packages → lawyer-api / lawyer-web → Package settings → Change visibility → Public)
**или** авторизуйтесь на сервере:
`echo <GITHUB_PAT c read:packages> | docker login ghcr.io -u <логин> --password-stdin`.

```bash
export COMPOSE_FILE=docker-compose.registry.yml
docker compose pull            # скачать готовые образы (быстро)
./scripts/init-letsencrypt.sh  # выпустить TLS-сертификат
docker compose up -d           # запустить
```

### Вариант B — сборка образов на сервере (медленно на слабом VPS)
```bash
export COMPOSE_FILE=docker-compose.prod.yml
./scripts/init-letsencrypt.sh  # соберёт образы и выпустит сертификат
docker compose up -d --build
```

В обоих случаях поднимутся: `db` (PostgreSQL 16), `api` (FastAPI, миграции
применяются автоматически), `worker` (планировщик), `web` (nginx + фронтенд, HTTPS),
`certbot` (автопродление).

Откройте **https://lawyer.futuguru.com** → страница входа → логин/пароль из `.env`.

> `init-letsencrypt.sh` требует, чтобы DNS (шаг 1) уже указывал на сервер и порт 80
> был открыт. По умолчанию скрипт берёт `docker-compose.registry.yml`; для сборки
> на сервере задайте `COMPOSE_FILE=docker-compose.prod.yml` (как в варианте B).
>
> **Сертификат выпускается один раз.** Скрипт идемпотентен: при уже действующем
> сертификате он ничего не перевыпускает (продление идёт автоматически сервисом
> `certbot`). Не запускайте его для обновлений кода — иначе можно упереться в лимит
> Let's Encrypt (5 сертификатов на домен за 168 часов). Осознанный перевыпуск:
> `./scripts/init-letsencrypt.sh --force`.

## 5a. Применение обновлений кода

После деплоя новой версии (образы собраны в GitHub Actions) обновление
применяется **одной командой** — без пересоздания сертификата:
```bash
./scripts/update.sh
# или сборка на сервере:
COMPOSE_FILE=docker-compose.prod.yml ./scripts/update.sh
```
Скрипт забирает свежие образы (или пересобирает), перезапускает изменившиеся
контейнеры (миграции БД `api` применяет сам при старте) и чистит устаревшие
образы. TLS-сертификат не затрагивается.

## 6. Переключение на боевые данные
1. Заполните доступы интеграций в `.env` (см. [INTEGRATIONS.md](INTEGRATIONS.md)).
2. Установите `DATA_SOURCE=real`.
3. Перезапустите и выполните первичную выгрузку (`COMPOSE_FILE` уже экспортирован):
```bash
docker compose up -d
docker compose exec api python -m app.services.ingest
```
Далее выгрузка и пересчёт идут по расписанию (планировщик `worker`).

## 8. Резервное копирование
Ручной бэкап БД:
```bash
./scripts/backup_db.sh          # создаст backups/lawyer_<дата>.sql.gz
```
Автоматически (ежедневно в 03:00) — добавьте в crontab:
```bash
crontab -e
# 0 3 * * * cd /opt/lawyer && ./scripts/backup_db.sh >> /var/log/lawyer-backup.log 2>&1
```

## Проверка и обслуживание
- Логи: `docker compose -f docker-compose.prod.yml logs -f api worker web`
- Статус: `docker compose -f docker-compose.prod.yml ps`
- Обновление кода: `./scripts/update.sh` (не трогает TLS-сертификат)
- Подробнее — [ADMIN.md](ADMIN.md).

## Частые вопросы
- **Сертификат не выпустился** — проверьте `dig +short lawyer.futuguru.com` (должен быть IP VPS) и что порт 80 открыт. Если в логе `too many certificates ... in the last 168h` — это лимит Let's Encrypt: дождитесь времени, указанного в ошибке (`retry after ...`), и запустите `./scripts/init-letsencrypt.sh` снова. Не перевыпускайте сертификат ради обновлений кода — для них есть `./scripts/update.sh`.
- **Браузер пишет `NET::ERR_CERT_AUTHORITY_INVALID`** — nginx отдаёт временный самоподписанный сертификат (боевой не выпущен или удалён). Выпустите боевой: `./scripts/init-letsencrypt.sh` (при активном лимите — после окончания недельного окна).
- **Упёрлись в лимит Let's Encrypt, а сайт нужен сейчас** — лимит считается на *точный набор доменов*. Добавьте в сертификат ещё один домен, и это будет новый набор (свой лимит): создайте A-запись `www.<домен>` → IP VPS, укажите в `.env` `CERT_EXTRA_DOMAINS=www.<домен>` и запустите `./scripts/init-letsencrypt.sh`. Сертификат выпустится на оба домена сразу. У каждого домена в сертификате должна быть A-запись на этот VPS — иначе проверка не пройдёт.
- **Не скачался Russian Trusted CA при сборке** (нужен для API росс. сервисов) — см. раздел «Russian Trusted CA» в [ADMIN.md](ADMIN.md).
- **502 на /api** — контейнер `api` ещё стартует (миграции); подождите и проверьте логи.
