// ПРОФИЛЬ B — аутентифицированные чтения (ТЗ п.80).
//
// Главный вопрос профиля: действительно ли Redis-кэш личности убирает
// SELECT Student на каждом запросе. Проверяется не рассуждением, а
// сравнением метрик приложения до и после прогона — /metrics покажет,
// росло ли число запросов к базе пропорционально нагрузке.

import http from 'k6/http';
import { BASE_URL, DURATION, MAX_VUS, RAMP_UP, SLO, TARGET_RPS, VUS, authHeaders, loadFixtures } from './lib/config.js';
import { checkRead } from './lib/checks.js';

const fixtures = loadFixtures();

export const options = {
  scenarios: {
    auth_read: {
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
    'http_req_duration{expected_response:true}': [`p(95)<${SLO.authReadP95}`],
    server_errors: [`rate<${SLO.maxServerErrorRate}`],
  },
};

export default function () {
  // Уникальные студенты: один и тот же токен мерил бы попадание
  // в кэш одной записи, а не работу кэша под нагрузкой
  const student = fixtures.students[Math.floor(Math.random() * fixtures.students.length)];
  const election = fixtures.elections[Math.floor(Math.random() * fixtures.elections.length)];
  const opts = authHeaders(student.token);

  const roll = Math.random();
  if (roll < 0.4) {
    checkRead(http.get(`${BASE_URL}/api/v1/elections/available/`, opts), 'available');
  } else if (roll < 0.7) {
    checkRead(http.get(`${BASE_URL}/api/v1/elections/${election.id}/`, opts), 'detail');
  } else {
    checkRead(http.get(`${BASE_URL}/api/v1/voting/status/${election.id}/`, opts), 'status');
  }
}
