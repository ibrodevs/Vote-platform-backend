#!/usr/bin/env bash
# Запуск нагрузочного сценария (ТЗ п.77).
#
# Обязательная последовательность, а не просто «запустить k6»:
#   1. снять состояние данных ДО прогона
#   2. прогнать сценарий
#   3. ПРОВЕРИТЬ ЦЕЛОСТНОСТЬ ДАННЫХ
#
# Шаг 3 не опционален. ТЗ п.87: нагрузка без проверки целостности
# не считается валидным бенчмарком.
#
#   ./loadtests/run.sh profile_a_public_read
#   TARGET_RPS=500 DURATION=60s ./loadtests/run.sh profile_c_mixed

set -euo pipefail

SCENARIO="${1:?Укажите сценарий, например profile_a_public_read}"
COMPOSE="${COMPOSE:-docker compose}"
NETWORK="${NETWORK:-vote-platform-backend_default}"
RESULTS_DIR="${RESULTS_DIR:-loadtests/results}"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$RESULTS_DIR"

echo "=== Окружение (ТЗ п.108) ==="
{
  echo "scenario:   $SCENARIO"
  echo "timestamp:  $STAMP"
  echo "commit:     $(git rev-parse --short HEAD)"
  echo "target_rps: ${TARGET_RPS:-200}"
  echo "duration:   ${DURATION:-30s}"
  $COMPOSE exec -T web python -c "import django,sys;print('django:     '+django.get_version());print('python:     '+sys.version.split()[0])"
  $COMPOSE exec -T postgres postgres --version | sed 's/^/postgres:   /'
  docker info --format 'docker_cpu:  {{.NCPU}}' 2>/dev/null || true
  docker info --format '{{.MemTotal}}' 2>/dev/null | awk '{printf "docker_mem:  %.1f GiB\n", $1/1073741824}' || true
} | tee "$RESULTS_DIR/$SCENARIO-$STAMP.env"

echo
echo "=== Состояние данных ДО прогона ==="
$COMPOSE exec -T web python manage.py verify_election_integrity --quiet \
  | tee "$RESULTS_DIR/$SCENARIO-$STAMP.before"

echo
echo "=== Прогон ==="
docker run --rm -i --network "$NETWORK" \
  -v "$PWD/loadtests/k6:/scripts:ro" \
  -v "$PWD/loadtests/fixtures:/fixtures:ro" \
  -e BASE_URL="${BASE_URL:-http://web:8000}" \
  -e TARGET_RPS="${TARGET_RPS:-200}" \
  -e DURATION="${DURATION:-30s}" \
  -e RAMP_UP="${RAMP_UP:-10s}" \
  -e VUS="${VUS:-50}" \
  -e MAX_VUS="${MAX_VUS:-300}" \
  -e SLO_ERROR_RATE="${SLO_ERROR_RATE:-0.001}" \
  grafana/k6:latest run "/scripts/$SCENARIO.js" \
  2>&1 | tee "$RESULTS_DIR/$SCENARIO-$STAMP.log" || K6_FAILED=1

echo
echo "=== ОБЯЗАТЕЛЬНАЯ проверка целостности (ТЗ п.87) ==="
$COMPOSE exec -T web python manage.py verify_election_integrity \
  | tee "$RESULTS_DIR/$SCENARIO-$STAMP.after"

echo
echo "Результаты: $RESULTS_DIR/$SCENARIO-$STAMP.*"
exit "${K6_FAILED:-0}"
