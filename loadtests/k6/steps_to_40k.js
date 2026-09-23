// ЛЕСТНИЦА СТУПЕНЕЙ 1k -> 5k -> 10k -> 20k -> 40k RPS (ТЗ п.85, 108).
//
// Отдельный сценарий, а не параметр: смысл ступеней в том, чтобы увидеть,
// НА КАКОЙ ИМЕННО ступени система перестаёт держать SLO. Пять отдельных
// прогонов этого не показывают — между ними успевают прогреться кэши,
// смениться планы запросов и сброситься счётчики.
//
// ЭТОТ СЦЕНАРИЙ НЕ ПРЕДНАЗНАЧЕН ДЛЯ НОУТБУКА. На машине, где генератор
// делит ядра с приложением и базой, он измерит генератор. Запускать
// с выделенных нагрузочных узлов против настоящей инфраструктуры.
//
//   BASE_URL=https://api.example.org ./loadtests/run.sh steps_to_40k
//   STEP_DURATION=3m ./loadtests/run.sh steps_to_40k
//
// Порог считается нарушенным, если на ступени p95 вышел за SLO или
// появились ошибки 5xx. Ступень, на которой это произошло, и есть ответ.

import http from 'k6/http';
import { BASE_URL, MAX_VUS, SLO, VUS } from './lib/config.js';
import { checkRead, serverErrors } from './lib/checks.js';

// Ступени из ТЗ. Переопределяются только ради дымовой проверки самого
// сценария (LADDER=50,100) — как контракт на измерение они остаются
// такими, какими их задало ТЗ.
const LADDER = (__ENV.LADDER || '1000,5000,10000,20000,40000')
  .split(',')
  .map((v) => parseInt(v.trim(), 10))
  .filter((v) => Number.isFinite(v) && v > 0);

const STEP_DURATION = __ENV.STEP_DURATION || '2m';
const RAMP_BETWEEN = __ENV.RAMP_BETWEEN || '30s';

// Каждая ступень — подъём и удержание. Удержание обязательно: система,
// пережившая мгновенный пик, может не пережить две минуты на нём же.
const stages = [];
for (const target of LADDER) {
  stages.push({ target, duration: RAMP_BETWEEN });
  stages.push({ target, duration: STEP_DURATION });
}

export const options = {
  scenarios: {
    ladder: {
      executor: 'ramping-arrival-rate',
      startRate: 100,
      timeUnit: '1s',
      preAllocatedVUs: VUS,
      // На 40k RPS виртуальных пользователей нужно намного больше, чем
      // в обычных профилях: при задержке 100 мс это 4000 одновременных.
      maxVUs: Math.max(MAX_VUS, 8000),
      stages,
    },
  },
  thresholds: {
    'http_req_duration{expected_response:true}': [`p(95)<${SLO.cachedReadP95}`],
    server_errors: [`rate<${SLO.maxServerErrorRate}`],
  },
};

// Публичные кэшируемые чтения: именно они обязаны масштабироваться до
// заявленных величин. Запись голосов на таких числах измеряется отдельно
// профилем D — 40k HTTP RPS и 40k записей в секунду это разные величины.
const ENDPOINTS = [
  '/api/v1/universities/',
  '/api/v1/elections/recent/',
  '/api/v1/faqs/',
  '/api/v1/news/',
];

export default function () {
  const path = ENDPOINTS[Math.floor(Math.random() * ENDPOINTS.length)];
  checkRead(http.get(`${BASE_URL}${path}`), path);
}

export function handleSummary(data) {
  const p95 = data.metrics.http_req_duration?.values?.['p(95)'];
  const errors = data.metrics.server_errors?.values?.rate ?? 0;
  const reqs = data.metrics.http_reqs?.values?.rate ?? 0;
  return {
    stdout: [
      '',
      '=== Лестница ступеней ===',
      `ступени:        ${LADDER.join(' -> ')} RPS`,
      `удержание:      ${STEP_DURATION} на ступень`,
      `фактический RPS: ${reqs.toFixed(1)}`,
      `p95:            ${p95 ? p95.toFixed(1) : 'н/д'} мс`,
      `ошибки 5xx:     ${(errors * 100).toFixed(3)} %`,
      '',
      'Фактический RPS заметно ниже заданного означает, что система',
      'не приняла нагрузку — ищите последнюю ступень, где они совпадали.',
      '',
    ].join('\n'),
  };
}
