#!/usr/bin/env bash
# ==============================================================================
# Preflight Verification Script for Vote Platform Backend
# Hetzner Cloud HEL1 — CCX33 (Ubuntu 24.04 LTS)
# ==============================================================================
# Проверяет готовность сервера и конфигурации к запуску production-деплоя.
# НЕ выводит секреты в консоль.
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

pass() {
    echo -e "  [${GREEN}OK${NC}] $1"
}

warn() {
    echo -e "  [${YELLOW}WARN${NC}] $1"
    WARNINGS=$((WARNINGS + 1))
}

fail() {
    echo -e "  [${RED}FAIL${NC}] $1"
    ERRORS=$((ERRORS + 1))
}

info() {
    echo -e "${BLUE}==>${NC} $1"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${BACKEND_DIR}"

echo "=================================================================="
echo " Vote Platform Backend: Preflight System Verification"
echo "=================================================================="

# ------------------------------------------------------------------------------
# 1. Проверка Docker и Docker Compose
# ------------------------------------------------------------------------------
info "Проверка Docker окружения..."

if [ "${SKIP_DOCKER_CHECK:-0}" = "1" ]; then
    warn "Проверка Docker окружения пропущена (SKIP_DOCKER_CHECK=1)"
else
    if command -v docker >/dev/null 2>&1; then
        pass "Docker CLI установлен: $(docker --version)"
        if docker info >/dev/null 2>&1; then
            pass "Docker daemon доступен и отвечает"
        else
            fail "Docker daemon не запущен или текущий пользователь не входит в группу docker"
        fi
    else
        fail "Docker не установлен. Установите Docker: https://docs.docker.com/engine/install/ubuntu/"
    fi

    if docker compose version >/dev/null 2>&1; then
        pass "Docker Compose v2 доступен: $(docker compose version)"
    else
        fail "Docker Compose v2 не найден (требуется docker compose v2.x)"
    fi
fi

# ------------------------------------------------------------------------------
# 2. Проверка конфигурации .env
# ------------------------------------------------------------------------------
info "Проверка файла конфигурации (.env)..."

ENV_FILE="${1:-${BACKEND_DIR}/.env}"
if [ -f "${ENV_FILE}" ]; then
    pass "Файл конфигурации найден: ${ENV_FILE}"
else
    fail "Файл конфигурации отсутствует (${ENV_FILE})! Скопируйте шаблон: cp .env.example .env и задайте секреты"
fi

validate_domain() {
    local domain="$1"
    if [[ ! "${domain}" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ ]] || [[ "${domain}" =~ [\/:\;[:space:]\$\`\\] ]] || [[ "${domain}" == *".."* ]]; then
        return 1
    fi
    return 0
}

validate_ip_or_cidr() {
    local ip="$1"
    if [[ "${ip}" =~ [^a-fA-F0-9.:/] ]] || [ -z "${ip}" ]; then
        return 1
    fi
    local ipv4_cidr_regex="^([0-9]{1,3}\.){3}[0-9]{1,3}(/([0-9]|[1-2][0-9]|3[0-2]))?$"
    local ipv6_cidr_regex="^([0-9a-fA-F]{0,4}:){1,7}[0-9a-fA-F]{0,4}(/([0-9]|[1-9][0-9]|1[0-1][0-9]|12[0-8]))?$"

    if [[ "${ip}" =~ $ipv4_cidr_regex ]]; then
        local base_ip="${ip%%/*}"
        IFS='.' read -r o1 o2 o3 o4 <<< "$base_ip"
        if [ "$o1" -le 255 ] && [ "$o2" -le 255 ] && [ "$o3" -le 255 ] && [ "$o4" -le 255 ]; then
            return 0
        fi
        return 1
    elif [[ "${ip}" =~ $ipv6_cidr_regex ]] && [[ "${ip}" == *":"* ]]; then
        return 0
    fi
    return 1
}

# Загружаем переменные из .env безопасно для проверок
if [ -f "${ENV_FILE}" ]; then
    get_env() {
        grep -E "^${1}=" "${ENV_FILE}" | cut -d '=' -f2- | tr -d '"' | tr -d "'" | tr -d '\r' | xargs || true
    }

    DJANGO_ENV_VAL="$(get_env DJANGO_ENV)"
    STAGE_VAL="$(get_env DEPLOYMENT_STAGE)"
    STAGE_VAL="${STAGE_VAL:-bootstrap}"
    SECRET_KEY_VAL="$(get_env DJANGO_SECRET_KEY)"
    ALLOWED_HOSTS_VAL="$(get_env DJANGO_ALLOWED_HOSTS)"
    CORS_VAL="$(get_env DJANGO_CORS_ALLOWED_ORIGINS)"
    DB_PASS_VAL="$(get_env DB_PASSWORD)"
    REDIS_PASS_VAL="$(get_env REDIS_PASSWORD)"
    REDIS_URL_VAL="$(get_env REDIS_URL)"
    CELERY_BROKER_VAL="$(get_env CELERY_BROKER_URL)"
    DB_BEHIND_PG_VAL="$(get_env DB_BEHIND_PGBOUNCER)"
    DB_CONN_AGE_VAL="$(get_env DB_CONN_MAX_AGE)"
    API_DOMAIN_VAL="$(get_env API_DOMAIN)"
    ADMIN_ALLOWED_IP_VAL="$(get_env ADMIN_ALLOWED_IP)"
    NGINX_CONF_VAL="$(get_env NGINX_CONF_FILE)"
    NGINX_CONF_VAL="${NGINX_CONF_VAL:-http.conf}"

    # DJANGO_ENV
    if [ "${DJANGO_ENV_VAL}" = "production" ]; then
        pass "DJANGO_ENV=production"
    else
        fail "DJANGO_ENV должен быть 'production' (получено '${DJANGO_ENV_VAL}')"
    fi

    # DJANGO_SECRET_KEY
    LEAKED_KEY="vote-platform-secret-key-34e8bb-midnight-011c42"
    if [ -z "${SECRET_KEY_VAL}" ]; then
        fail "DJANGO_SECRET_KEY не задан!"
    elif [ "${SECRET_KEY_VAL}" = "${LEAKED_KEY}" ]; then
        fail "DJANGO_SECRET_KEY содержит скомпрометированный ключ из репозитория! Смените немедленно"
    elif [ "${#SECRET_KEY_VAL}" -lt 32 ]; then
        fail "DJANGO_SECRET_KEY короче 32 символов (текущая длина: ${#SECRET_KEY_VAL})"
    else
        pass "DJANGO_SECRET_KEY задан и имеет надёжную длину (${#SECRET_KEY_VAL} симв.)"
    fi

    # Пароли БД и Redis
    if [ -z "${DB_PASS_VAL}" ]; then
        fail "DB_PASSWORD не задан"
    elif [ "${#DB_PASS_VAL}" -lt 16 ]; then
        warn "DB_PASSWORD короче 16 символов"
    else
        pass "DB_PASSWORD задан"
    fi

    if [ -z "${REDIS_PASS_VAL}" ]; then
        fail "REDIS_PASSWORD не задан"
    elif [ "${#REDIS_PASS_VAL}" -lt 16 ]; then
        warn "REDIS_PASSWORD короче 16 символов"
    else
        pass "REDIS_PASSWORD задан"
    fi

    # Проверка на незаменённые плейсхолдеры в URL
    if [[ "${REDIS_URL_VAL}" == *"<REDIS_PASSWORD>"* ]] || [[ "${REDIS_URL_VAL}" == *"пароль"* ]]; then
        fail "REDIS_URL содержит незаменённый плейсхолдер пароля"
    else
        pass "REDIS_URL сконфигурирован"
    fi

    if [[ "${CELERY_BROKER_VAL}" == *"<REDIS_PASSWORD>"* ]] || [[ "${CELERY_BROKER_VAL}" == *"пароль"* ]]; then
        fail "CELERY_BROKER_URL содержит незаменённый плейсхолдер пароля"
    else
        pass "CELERY_BROKER_URL сконфигурирован"
    fi

    # ALLOWED_HOSTS
    if [ -z "${ALLOWED_HOSTS_VAL}" ]; then
        fail "DJANGO_ALLOWED_HOSTS пуст! Укажите IP сервера или домен"
    elif [[ "${ALLOWED_HOSTS_VAL}" == *"*"* ]]; then
        fail "DJANGO_ALLOWED_HOSTS содержит wildcard '*' (запрещено в production)"
    else
        pass "DJANGO_ALLOWED_HOSTS: ${ALLOWED_HOSTS_VAL}"
    fi

    # CORS
    if [ -z "${CORS_VAL}" ]; then
        fail "DJANGO_CORS_ALLOWED_ORIGINS пуст! Фронтенд не сможет отправлять запросы"
    elif [[ "${CORS_VAL}" == *"*"* ]]; then
        fail "DJANGO_CORS_ALLOWED_ORIGINS содержит wildcard '*' (запрещено)"
    else
        pass "DJANGO_CORS_ALLOWED_ORIGINS: ${CORS_VAL}"
    fi

    # PgBouncer пара
    if [ "${DB_BEHIND_PG_VAL}" = "True" ] && [ "${DB_CONN_AGE_VAL}" = "0" ]; then
        pass "DB_BEHIND_PGBOUNCER=True и DB_CONN_MAX_AGE=0 (корректная пара для transaction pooling)"
    else
        fail "Неверная конфигурация PgBouncer! Требуется DB_BEHIND_PGBOUNCER=True и DB_CONN_MAX_AGE=0"
    fi

    # Согласованность stage <-> NGINX_CONF_FILE (ТЗ п.7)
    if [ "${STAGE_VAL}" = "bootstrap" ]; then
        if [ "${NGINX_CONF_VAL}" = "http.conf" ]; then
            pass "Согласованность stage/config: DEPLOYMENT_STAGE=bootstrap и NGINX_CONF_FILE=http.conf"
        else
            fail "Несогласованная конфигурация: DEPLOYMENT_STAGE=bootstrap требует NGINX_CONF_FILE=http.conf (получено: '${NGINX_CONF_VAL}')"
        fi
    elif [ "${STAGE_VAL}" = "production" ]; then
        if [ "${NGINX_CONF_VAL}" = "https.conf" ]; then
            pass "Согласованность stage/config: DEPLOYMENT_STAGE=production и NGINX_CONF_FILE=https.conf"
        else
            fail "Несогласованная конфигурация: DEPLOYMENT_STAGE=production требует NGINX_CONF_FILE=https.conf (получено: '${NGINX_CONF_VAL}')"
        fi
    else
        warn "Нестандартный DEPLOYMENT_STAGE: '${STAGE_VAL}' (рекомендуется 'bootstrap' или 'production')"
    fi

    # Валидация API_DOMAIN (ТЗ п.10)
    if [ "${STAGE_VAL}" = "production" ]; then
        if [ -z "${API_DOMAIN_VAL}" ]; then
            fail "DEPLOYMENT_STAGE=production требует обязательного указания API_DOMAIN в .env (например: api.example.com)"
        elif ! validate_domain "${API_DOMAIN_VAL}"; then
            fail "API_DOMAIN содержит недопустимые символы: '${API_DOMAIN_VAL}' (разрешены только буквы, цифры, дефис и точка)"
        else
            pass "API_DOMAIN валиден: ${API_DOMAIN_VAL}"
        fi
    elif [ -n "${API_DOMAIN_VAL}" ]; then
        if ! validate_domain "${API_DOMAIN_VAL}"; then
            fail "API_DOMAIN содержит недопустимые символы: '${API_DOMAIN_VAL}'"
        else
            pass "API_DOMAIN валиден: ${API_DOMAIN_VAL}"
        fi
    fi

    # Валидация ADMIN_ALLOWED_IP (ТЗ п.11, 12)
    if [ "${STAGE_VAL}" = "production" ]; then
        if [ -z "${ADMIN_ALLOWED_IP_VAL}" ]; then
            fail "В режиме DEPLOYMENT_STAGE=production переменная ADMIN_ALLOWED_IP обязательна для ограничения доступа к панели управления Django (ТЗ п.12)"
        elif ! validate_ip_or_cidr "${ADMIN_ALLOWED_IP_VAL}"; then
            fail "ADMIN_ALLOWED_IP содержит некорректный IP/CIDR адрес: '${ADMIN_ALLOWED_IP_VAL}' (ожидается IPv4, IPv6 или CIDR)"
        else
            pass "ADMIN_ALLOWED_IP валиден: ${ADMIN_ALLOWED_IP_VAL} (доступ к Django admin ограничен)"
        fi
    else
        if [ -z "${ADMIN_ALLOWED_IP_VAL}" ]; then
            warn "ADMIN_ALLOWED_IP не задан — в bootstrap-режиме Django admin открыт без ограничения по IP"
        elif ! validate_ip_or_cidr "${ADMIN_ALLOWED_IP_VAL}"; then
            fail "ADMIN_ALLOWED_IP содержит некорректный IP/CIDR адрес: '${ADMIN_ALLOWED_IP_VAL}'"
        else
            pass "ADMIN_ALLOWED_IP валиден: ${ADMIN_ALLOWED_IP_VAL}"
        fi
    fi

    # Проверка TLS-сертификатов для production (ТЗ п.8, 9)
    if [ "${STAGE_VAL}" = "production" ]; then
        CERT_DIR="${BACKEND_DIR}/deploy/certs"
        FULLCHAIN="${CERT_DIR}/fullchain.pem"
        PRIVKEY="${CERT_DIR}/privkey.pem"

        if [ ! -f "${FULLCHAIN}" ] || [ ! -s "${FULLCHAIN}" ]; then
            fail "Отсутствует или пуст TLS сертификат: deploy/certs/fullchain.pem (обязателен в production)"
        elif [ ! -f "${PRIVKEY}" ] || [ ! -s "${PRIVKEY}" ]; then
            fail "Отсутствует или пуст приватный ключ TLS: deploy/certs/privkey.pem (обязателен в production)"
        else
            pass "Файлы deploy/certs/fullchain.pem и privkey.pem присутствуют"
            if command -v openssl >/dev/null 2>&1; then
                if openssl x509 -in "${FULLCHAIN}" -noout >/dev/null 2>&1; then
                    pass "Синтаксис сертификата deploy/certs/fullchain.pem валиден"
                else
                    fail "Файл deploy/certs/fullchain.pem не является валидным X.509 сертификатом!"
                fi

                if openssl pkey -in "${PRIVKEY}" -check -noout >/dev/null 2>&1; then
                    pass "Синтаксис приватного ключа deploy/certs/privkey.pem валиден"
                else
                    fail "Файл deploy/certs/privkey.pem повреждён или не является валидным закрытым ключом!"
                fi
            fi
        fi
    fi
fi

# ------------------------------------------------------------------------------
# 3. Проверка аппаратных ресурсов (Hetzner CCX33: 8 CPU, 32GB RAM, 240GB NVMe)
# ------------------------------------------------------------------------------
info "Проверка аппаратных ресурсов сервера..."

# RAM
TOTAL_MEM_KB=0
if [ -f /proc/meminfo ]; then
    TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    TOTAL_MEM_GB=$((TOTAL_MEM_KB / 1024 / 1024))
    if [ "${TOTAL_MEM_GB}" -ge 28 ]; then
        pass "Оперативная память: ${TOTAL_MEM_GB} GB (соответствует CCX33 32 GB)"
    elif [ "${TOTAL_MEM_GB}" -ge 14 ]; then
        warn "Оперативная память: ${TOTAL_MEM_GB} GB (меньше ожидаемых 32 GB для CCX33)"
    else
        fail "Оперативная память: ${TOTAL_MEM_GB} GB (недостаточно для CCX33 production стека)"
    fi
elif command -v sysctl >/dev/null 2>&1; then
    # macOS fallback
    TOTAL_MEM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    TOTAL_MEM_GB=$((TOTAL_MEM_BYTES / 1024 / 1024 / 1024))
    pass "Оперативная память (хост): ${TOTAL_MEM_GB} GB"
fi

# Диск
DISK_AVAIL_KB=$(df -k "${BACKEND_DIR}" | awk 'NR==2 {print $4}')
DISK_AVAIL_GB=$((DISK_AVAIL_KB / 1024 / 1024))
if [ "${DISK_AVAIL_GB}" -ge 20 ]; then
    pass "Доступно свободного места на диске: ${DISK_AVAIL_GB} GB"
elif [ "${DISK_AVAIL_GB}" -ge 5 ]; then
    warn "Доступно места на диске: ${DISK_AVAIL_GB} GB (рекомендуется минимум 20 GB)"
else
    fail "Критически мало места на диске: ${DISK_AVAIL_GB} GB!"
fi

# Swap
if [ -f /proc/swaps ]; then
    SWAP_COUNT=$(grep -v Filename /proc/swaps | wc -l || echo 0)
    if [ "${SWAP_COUNT}" -gt 0 ]; then
        SWAP_KB=$(awk 'NR>1 {sum += $3} END {print sum}' /proc/swaps)
        SWAP_MB=$((SWAP_KB / 1024))
        pass "Swap настроен: ${SWAP_MB} MB"
    else
        warn "Swap не обнаружен. Рекомендуется настроить 2-4 GB swapfile (ТЗ п.20) как страховку от мгновенного OOM"
    fi
fi

# ------------------------------------------------------------------------------
# 4. Проверка портов (ТЗ п.6)
# ------------------------------------------------------------------------------
info "Проверка сетевых портов..."

get_port_listener() {
    local port=$1
    if command -v ss >/dev/null 2>&1; then
        ss -tuln 2>/dev/null | grep -E "[:\.]${port}\b" || true
    elif command -v netstat >/dev/null 2>&1; then
        netstat -tuln 2>/dev/null | grep -E "[:\.]${port}\b" || true
    elif command -v lsof >/dev/null 2>&1; then
        lsof -iTCP:"${port}" -sTCP:LISTEN -P -n 2>/dev/null || true
    fi
}

get_port_proc_info() {
    local port=$1
    if command -v ss >/dev/null 2>&1; then
        ss -tulpn 2>/dev/null | grep -E "[:\.]${port}\b" || true
    elif command -v lsof >/dev/null 2>&1; then
        lsof -iTCP:"${port}" -sTCP:LISTEN -P -n 2>/dev/null || true
    elif command -v netstat >/dev/null 2>&1; then
        netstat -tulpn 2>/dev/null | grep -E "[:\.]${port}\b" || true
    fi
}

check_public_port() {
    local port=$1
    local listener
    listener=$(get_port_listener "${port}")
    if [ -n "${listener}" ]; then
        local proc_info
        proc_info=$(get_port_proc_info "${port}" | head -n 1 | xargs || true)

        # Проверка: занят ли порт Docker-контейнером нашего проекта
        local is_our_container=false
        local container_name=""
        if command -v docker >/dev/null 2>&1; then
            container_name=$(docker ps --filter "publish=${port}" --format '{{.Names}} ({{.Image}})' 2>/dev/null | head -n 1 || true)
            if [ -n "${container_name}" ]; then
                local compose_project
                compose_project=$(basename "${BACKEND_DIR}" | tr '[:upper:]' '[:lower:]' | tr -cd '[:alnum:]_-')
                if [[ "${container_name}" == *"nginx"* ]] || [[ "${container_name}" == *"${compose_project}"* ]] || [[ "${container_name}" == *"vote"* ]]; then
                    is_our_container=true
                fi
            fi
        fi

        if [ "${is_our_container}" = true ]; then
            pass "Порт ${port}/tcp занят контейнером текущего проекта: ${container_name} — обновление разрешено"
        else
            fail "Порт ${port}/tcp занят сторонним процессом: ${proc_info:-${listener}}! Освободите порт перед деплоем"
        fi
    else
        pass "Порт ${port}/tcp свободен"
    fi
}

check_internal_port() {
    local port=$1
    local name=$2
    local listener
    listener=$(get_port_listener "${port}")
    if [ -n "${listener}" ]; then
        # Проверяем, слушает ли порт на 0.0.0.0, ::: или * (все интерфейсы)
        if echo "${listener}" | grep -E "(0\.0\.0\.0|:::|\*)[:\.]${port}\b" >/dev/null 2>&1; then
            local proc_info
            proc_info=$(get_port_proc_info "${port}" | head -n 1 | xargs || true)
            fail "Внутренний порт ${port}/tcp (${name}) открыт наружу (0.0.0.0/*): ${proc_info:-${listener}}! Сервис должен быть изолирован в Docker-сети"
        else
            pass "Порт ${port}/tcp (${name}) привязан только к локальному интерфейсу (127.0.0.1)"
        fi
    else
        pass "Порт ${port}/tcp (${name}) не экспонирован наружу на хосте"
    fi
}

check_public_port 80
check_public_port 443

check_internal_port 5432 "PostgreSQL"
check_internal_port 6379 "Redis"
check_internal_port 6432 "PgBouncer"
check_internal_port 8000 "Gunicorn / App"

# ------------------------------------------------------------------------------
# 5. Проверка синтаксиса Docker Compose
# ------------------------------------------------------------------------------
info "Валидация docker-compose.prod.yml..."

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    if docker compose -f docker-compose.prod.yml config -q 2>/dev/null; then
        pass "docker-compose.prod.yml валиден"
    else
        fail "Ошибка в docker-compose.prod.yml! Запустите: docker compose -f docker-compose.prod.yml config"
    fi
fi

# ------------------------------------------------------------------------------
# Итог
# ------------------------------------------------------------------------------
echo "=================================================================="
if [ "${ERRORS}" -eq 0 ]; then
    echo -e "${GREEN}✓ Все критические проверки пройдены successfully!${NC}"
    if [ "${WARNINGS}" -gt 0 ]; then
        echo -e "${YELLOW}  (Обнаружено ${WARNINGS} предупреждений — ознакомьтесь выше)${NC}"
    fi
    echo "Сервер готов к запуску: ./scripts/deploy.sh"
    exit 0
else
    echo -e "${RED}✗ Обнаружено ${ERRORS} критических проблем!${NC}"
    echo "Исправьте указанные ошибки перед запуском деплоя."
    exit 1
fi
