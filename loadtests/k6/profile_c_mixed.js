// ПРОФИЛЬ C — смешанная реалистичная нагрузка (ТЗ п.81).
//
// Состав задан в ТЗ: 55% доступные выборы, 15% детали, 15% статус,
// 10% голосование, 5% прочее. Доли настраиваются переменными —
// реальный профиль дня выборов отличается от дня перед ними.

import http from 'k6/http';
import { BASE_URL, DURATION, MAX_VUS, RAMP_UP, SLO, TARGET_RPS, VUS, authHeaders, indexElectionsByUniversity, loadFixtures, pickEligible } from './lib/config.js';
import { checkRead, classifyVote } from './lib/checks.js';

const fixtures = loadFixtures();
const byUniversity = indexElectionsByUniversity(fixtures);

const MIX = {
  available: Number(__ENV.MIX_AVAILABLE || 55),
  detail: Number(__ENV.MIX_DETAIL || 15),
  status: Number(__ENV.MIX_STATUS || 15),
  vote: Number(__ENV.MIX_VOTE || 10),
  other: Number(__ENV.MIX_OTHER || 5),
};

export const options = {
  scenarios: {
    mixed: {
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
    server_errors: [`rate<${SLO.maxServerErrorRate}`],
    vote_duration: [`p(95)<${SLO.voteP95}`],
  },
};

export default function () {
  // Студент и выборы ОДНОГО вуза: иначе почти всё вернёт ineligible_student,
  // и профиль будет мерить отказы, а не работу системы
  const pair = pickEligible(fixtures, byUniversity, __VU * 997 + __ITER);
  if (!pair) return;
  const { student, election } = pair;
  const opts = authHeaders(student.token);

  const roll = Math.random() * 100;
  let cursor = 0;

  if (roll < (cursor += MIX.available)) {
    checkRead(http.get(`${BASE_URL}/api/v1/elections/available/`, opts), 'available');
  } else if (roll < (cursor += MIX.detail)) {
    checkRead(http.get(`${BASE_URL}/api/v1/elections/${election.id}/`, opts), 'detail');
  } else if (roll < (cursor += MIX.status)) {
    checkRead(http.get(`${BASE_URL}/api/v1/voting/status/${election.id}/`, opts), 'status');
  } else if (roll < (cursor += MIX.vote)) {
    const body = JSON.stringify({
      election_id: election.id,
      candidate_id: election.candidates[Math.floor(Math.random() * election.candidates.length)],
    });
    classifyVote(http.post(`${BASE_URL}/api/v1/voting/cast/`, body, opts));
  } else {
    checkRead(http.get(`${BASE_URL}/api/v1/universities/`), 'universities');
  }
}
