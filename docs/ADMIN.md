# Администрирование и эксплуатация

Все команды выполняются в каталоге проекта (`/opt/lawyer`) на сервере.
Прод-профиль: `docker compose -f docker-compose.prod.yml <команда>`.

## Управление сервисами
```bash
# Статус / логи
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api worker web

# Перезапуск / остановка / запуск
docker compose -f docker-compose.prod.yml restart api
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d
```

## Обновление версии
```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build   # миграции применяются автоматически
```

## Данные и бэкапы
```bash
# Резервная копия
./scripts/backup_db.sh

# Восстановление из копии
gunzip -c backups/lawyer_<дата>.sql.gz | \
  docker compose -f docker-compose.prod.yml exec -T db \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```
Рекомендуется cron: `0 3 * * * cd /opt/lawyer && ./scripts/backup_db.sh`.

## Переключение mock ↔ real
- `DATA_SOURCE=mock` — демо-данные прототипа (для проверки интерфейса).
- `DATA_SOURCE=real` — боевые интеграции. После смены:
  ```bash
  docker compose -f docker-compose.prod.yml up -d
  docker compose -f docker-compose.prod.yml exec api python -m app.services.ingest
  ```

## Планировщик (worker)
Регулярные задачи (см. `backend/app/worker.py`):
- сверка регламента — каждые 5 минут;
- выгрузка источников — ежечасно;
- ночной пересчёт аналитики (`ingest`) — 03:00;
- генерация AI-инсайтов — 03:30.
Ручной запуск выгрузки: `... exec api python -m app.services.ingest`.

## Админ-панель регламента
Раздел «Админ-панель регламента» в интерфейсе (доступ по логину администратора):
пороги этапов, правила задач, обязательные поля, рабочий график и производственный
календарь, логика создания задач, правило дублей, оценочные нарушения. Изменения
фиксируются в **истории с возможностью отката**; критичные параметры влияют на расчёт
нарушений сразу после сохранения.

## Russian Trusted CA (если не установился при сборке)
Сертификаты НУЦ Минцифры нужны для API российских сервисов. Если при сборке не было сети:
```bash
# Внутри контейнера api
docker compose -f docker-compose.prod.yml exec api sh -c '
  curl -fsSL https://gu-st.ru/content/Other/doc/russiantrustedca.pem \
    -o /usr/local/share/ca-certificates/russian-trusted-ca.crt && \
  update-ca-certificates && \
  cat /usr/local/share/ca-certificates/russian-trusted-ca.crt \
    >> "$(python -c "import certifi; print(certifi.where())")"'
docker compose -f docker-compose.prod.yml restart api worker
```

## TLS-сертификат
Автопродление выполняет контейнер `certbot` (каждые 12 часов) + перезагрузка nginx
(каждые 6 часов). Проверить срок: 
```bash
docker compose -f docker-compose.prod.yml run --rm --entrypoint \
  "certbot certificates" certbot
```

## Диагностика
- Здоровье API: `https://lawyer.futuguru.com/api/health` и `/api/health/db`.
- Swagger (в dev): `http://localhost:8000/api/docs`.
- Нет данных в боевом режиме — проверьте заполнение `.env` и логи `worker`/`api` после `ingest`.
