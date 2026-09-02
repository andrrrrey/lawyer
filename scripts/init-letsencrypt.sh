#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Первичный выпуск TLS-сертификата Let's Encrypt для домена из .env.
#
# ИДЕМПОТЕНТНО: если действующий боевой сертификат уже установлен — скрипт
# ничего не перевыпускает (продление идёт автоматически сервисом certbot).
# Это защищает от лимита Let's Encrypt (5 сертификатов на домен за 168 часов).
#
# Запускать этот скрипт нужно ОДИН раз при первичной настройке. Для применения
# обновлений кода используйте ./scripts/update.sh — он НЕ трогает сертификат.
#
# Принудительный перевыпуск (осознанно, помня о лимите):  ./scripts/init-letsencrypt.sh --force
#
# Предусловия: A-запись DOMAIN указывает на этот VPS; порт 80 открыт снаружи;
# .env заполнен (DOMAIN, LETSENCRYPT_EMAIL).
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
set -a; source .env; set +a

DOMAIN="${DOMAIN:?DOMAIN не задан в .env}"
EMAIL="${LETSENCRYPT_EMAIL:?LETSENCRYPT_EMAIL не задан в .env}"
FORCE="${1:-}"
# Доп. домены в сертификат (через пробел), напр. CERT_EXTRA_DOMAINS=www.lawyer.futuguru.com
# в .env. У каждого доп. домена должна быть A-запись на этот VPS (иначе выпуск упадёт).
EXTRA_DOMAINS="${CERT_EXTRA_DOMAINS:-}"
ALL_DOMAINS="${DOMAIN} ${EXTRA_DOMAINS}"
# Аргументы -d для certbot (первый домен = имя lineage → путь live/${DOMAIN}).
DARGS=""
for d in $ALL_DOMAINS; do DARGS="${DARGS} -d ${d}"; done
# По умолчанию — БЫСТРЫЙ путь: готовые образы из реестра (docker-compose.registry.yml).
# Для сборки на сервере: COMPOSE_FILE=docker-compose.prod.yml ./scripts/init-letsencrypt.sh
FILE="${COMPOSE_FILE:-docker-compose.registry.yml}"
COMPOSE="docker compose -f ${FILE}"
LIVE="/etc/letsencrypt/live/${DOMAIN}"
RENEW_MARGIN=$((30 * 24 * 3600))  # перевыпуск не нужен, пока > 30 дней до истечения

# Есть ли уже действующий сертификат Let's Encrypt, покрывающий ВСЕ нужные домены
# (не самоподписанный, не просроченный, со всеми доменами в SAN)?
has_valid_cert() {
  $COMPOSE run --rm -T --entrypoint sh certbot -c "
    F=${LIVE}/fullchain.pem
    [ -f \"\$F\" ] || exit 1
    openssl x509 -in \"\$F\" -noout -issuer 2>/dev/null | grep -qi encrypt || exit 1
    openssl x509 -in \"\$F\" -noout -checkend ${RENEW_MARGIN} >/dev/null 2>&1 || exit 1
    SANS=\$(openssl x509 -in \"\$F\" -noout -ext subjectAltName 2>/dev/null)
    for d in ${ALL_DOMAINS}; do echo \"\${SANS},\" | grep -q \"DNS:\$d,\" || exit 1; done
  " >/dev/null 2>&1
}

if [ "$FORCE" != "--force" ] && has_valid_cert; then
  echo "✓ Действующий сертификат Let's Encrypt уже установлен — перевыпуск не требуется."
  echo "  Продление выполняется автоматически (сервис certbot, каждые 12 ч)."
  echo "  Для применения обновлений кода: ./scripts/update.sh"
  $COMPOSE up -d web >/dev/null 2>&1 || true
  exit 0
fi

if [ "$FORCE" = "--force" ]; then
  echo "⚠ Принудительный перевыпуск (--force). Помните про лимит Let's Encrypt: 5/неделю."
fi

echo "==> 1/5 Подготовка образов (${FILE})"
# registry-режим: скачать готовые образы; build-режим: собрать. Лишнее — no-op.
$COMPOSE pull web api 2>/dev/null || true
$COMPOSE build web api 2>/dev/null || true

echo "==> 2/5 Временный самоподписанный сертификат (чтобы поднять nginx)"
$COMPOSE run --rm --entrypoint "sh -c \
  'mkdir -p ${LIVE} && openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
   -keyout ${LIVE}/privkey.pem -out ${LIVE}/fullchain.pem -subj /CN=${DOMAIN}'" certbot

echo "==> 3/5 Запуск nginx и ожидание готовности порта 80"
$COMPOSE up -d web
ready=0
for _ in $(seq 1 30); do
  if curl -sS -o /dev/null "http://localhost/.well-known/acme-challenge/ping" 2>/dev/null; then
    ready=1; break
  fi
  sleep 1
done
if [ "$ready" != "1" ]; then
  echo "ОШИБКА: nginx не отвечает на порту 80. Проверьте логи: $COMPOSE logs web"
  exit 1
fi

echo "==> 4/5 Выпуск боевого сертификата для: ${ALL_DOMAINS}"
$COMPOSE run --rm --entrypoint "rm -rf ${LIVE} \
  /etc/letsencrypt/archive/${DOMAIN} /etc/letsencrypt/renewal/${DOMAIN}.conf" certbot
if $COMPOSE run --rm --entrypoint "certbot certonly --webroot -w /var/www/certbot \
     ${DARGS} --cert-name ${DOMAIN} --expand --email ${EMAIL} --agree-tos \
     --no-eff-email --non-interactive" certbot; then
  echo "==> 5/5 Перезагрузка nginx с боевым сертификатом"
  $COMPOSE exec web nginx -s reload
  echo "Готово. Сертификат выпущен для: ${ALL_DOMAINS}."
  echo "Поднимите всю систему: docker compose up -d   (COMPOSE_FILE=${FILE})"
else
  echo "ОШИБКА выпуска сертификата. Восстанавливаю временный, чтобы nginx работал."
  $COMPOSE run --rm --entrypoint "sh -c \
    'mkdir -p ${LIVE} && openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
     -keyout ${LIVE}/privkey.pem -out ${LIVE}/fullchain.pem -subj /CN=${DOMAIN}'" certbot
  $COMPOSE restart web
  echo "Возможные причины: лимит Let's Encrypt (5/неделю на ТОЧНЫЙ набор доменов),"
  echo "закрытый порт 80, либо DNS одного из доменов (${ALL_DOMAINS}) не указывает"
  echo "на этот сервер. Каждый домен в сертификате проверяется отдельно — у всех"
  echo "должна быть A-запись на этот VPS. При лимите — дождитесь окончания окна"
  echo "(время в ошибке выше) или добавьте новый домен через CERT_EXTRA_DOMAINS."
  exit 1
fi
