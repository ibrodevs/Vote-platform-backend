// ПРОФИЛЬ A — публичные кэшируемые чтения (ТЗ п.79).
//
// Ступени 1k -> 5k -> 10k -> 20k -> 40k из ТЗ задаются переменной TARGET_RPS
// и запускаются на настоящей инфраструктуре. Здесь проверяется, что
// кэшируемое чтение вообще масштабируется линейно по нагрузке.

import http from 'k6/http';
import { BASE_URL, DURATION, MAX_VUS, RAMP_UP, SLO, TARGET_RPS, VUS } from './lib/config.js';
import { checkRead, serverErrors } from './lib/checks.js';

export const options = {
  scenarios: {
    public_read: {
      executor: 'ramping-arrival-rate',
      startRate: Math.max(1, Math.floor(TARGET_RPS / 10)),
      timeUnit: '1s',
      preAllocatedVUs: VUS,
      maxVUs: MAX_VUS,
      stages: [
        { target: TARGET_RPS, duration: RAMP_UP },
        { target: TARGET_RPS, duration: DURATION },
      ],
    },
  },
  thresholds: {
    'http_req_duration{expected_response:true}': [`p(95)<${SLO.cachedReadP95}`],
    server_errors: [`rate<${SLO.maxServerErrorRate}`],
  },
};

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
