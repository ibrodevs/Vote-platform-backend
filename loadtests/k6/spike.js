// SPIKE — резкий рост нагрузки (ТЗ п.111).
//
// Проверяется не пропускная способность, а отсутствие каскадного отказа:
// после всплеска система обязана продолжать работать, а не уйти в штопор
// из-за накопившейся очереди запросов.

import http from 'k6/http';
import { BASE_URL, MAX_VUS, SLO, TARGET_RPS, VUS, authHeaders, loadFixtures } from './lib/config.js';
import { checkRead } from './lib/checks.js';

const fixtures = loadFixtures();
const BASE_RATE = Math.max(1, Math.floor(TARGET_RPS / 10));

export const options = {
  scenarios: {
    spike: {
      executor: 'ramping-arrival-rate',
      startRate: BASE_RATE,
      timeUnit: '1s',
      preAllocatedVUs: VUS,
      maxVUs: MAX_VUS,
      stages: [
        { target: BASE_RATE, duration: '10s' },      // спокойный фон
        { target: TARGET_RPS, duration: '5s' },      // всплеск
        { target: TARGET_RPS, duration: '15s' },     // удержание
        { target: BASE_RATE, duration: '5s' },       // спад
        { target: BASE_RATE, duration: '15s' },      // восстановление
      ],
    },
  },
  thresholds: {
    // Порог мягче обычного: во время всплеска просадка допустима,
    // недопустим отказ
    server_errors: ['rate<0.05'],
  },
};

export default function () {
  const student = fixtures.students[Math.floor(Math.random() * fixtures.students.length)];
  checkRead(
    http.get(`${BASE_URL}/api/v1/elections/available/`, authHeaders(student.token)),
    'available',
  );
}
