// SOAK — длительная нагрузка (ТЗ п.110).
//
// Ищет то, что не видно на коротком прогоне: утечки памяти, утечки
// соединений, дрейф задержки, растущий backlog Celery. Полноценный soak —
// 30–60 минут; длительность задаётся переменной DURATION.

import http from 'k6/http';
import { BASE_URL, DURATION, MAX_VUS, SLO, TARGET_RPS, VUS, authHeaders, loadFixtures } from './lib/config.js';
import { checkRead } from './lib/checks.js';

const fixtures = loadFixtures();

export const options = {
  scenarios: {
    soak: {
      executor: 'constant-arrival-rate',
      rate: TARGET_RPS,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: VUS,
      maxVUs: MAX_VUS,
    },
  },
  thresholds: {
    server_errors: [`rate<${SLO.maxServerErrorRate}`],
    // Дрейф задержки — главный признак утечки. Порог по всему прогону
    // поймает постепенную деградацию, которой не видно в моменте.
    'http_req_duration{expected_response:true}': [`p(95)<${SLO.authReadP95}`],
  },
};

export default function () {
  const student = fixtures.students[Math.floor(Math.random() * fixtures.students.length)];
  const opts = authHeaders(student.token);
  const election = fixtures.elections[Math.floor(Math.random() * fixtures.elections.length)];

  if (Math.random() < 0.5) {
    checkRead(http.get(`${BASE_URL}/api/v1/elections/available/`, opts), 'available');
  } else {
    checkRead(http.get(`${BASE_URL}/api/v1/voting/status/${election.id}/`, opts), 'status');
  }
}
