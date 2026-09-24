// ПРОФИЛЬ D — только запись голосов (ТЗ п.82).
//
// ГЛАВНОЕ, ЧТО ЭТОТ ПРОФИЛЬ СУЩЕСТВУЕТ ОТДЕЛЬНО
// ---------------------------------------------
// 40k HTTP RPS и 40k durable vote writes в секунду — разные величины,
// и путать их нельзя. Один голос создаёт минимум две строки в PostgreSQL
// плюс записи в индексы и WAL, и всё это должно быть зафиксировано
// на диске до того, как клиент получит успех.
//
// Поэтому максимальная скорость записи измеряется отдельно, и упирается
// она в WAL, IOPS и блокировки, а не в CPU приложения.
//
// КАЖДЫЙ СТУДЕНТ ГОЛОСУЕТ ОДИН РАЗ. Повторные попытки давали бы
// already_voted, который стоит дешевле настоящей записи и завысил бы
// результат в разы.

import exec from 'k6/execution';
import http from 'k6/http';
import { BASE_URL, DURATION, MAX_VUS, RAMP_UP, SLO, TARGET_RPS, VUS, authHeaders, indexElectionsByUniversity, loadFixtures, pickEligible } from './lib/config.js';
import { classifyVote } from './lib/checks.js';

const fixtures = loadFixtures();
const byUniversity = indexElectionsByUniversity(fixtures);

export const options = {
  scenarios: {
    vote_write: {
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
    vote_duration: [`p(95)<${SLO.voteP95}`],
    server_errors: [`rate<${SLO.maxServerErrorRate}`],
  },
};

export default function () {
  // Сквозной номер итерации: каждый студент голосует РОВНО ОДИН раз.
  // Повторные попытки давали бы already_voted, который стоит дешевле
  // настоящей записи и завысил бы результат в разы.
  const index = exec.scenario.iterationInTest;
  const pair = pickEligible(fixtures, byUniversity, index);
  if (!pair) return;
  const { student, election } = pair;

  const body = JSON.stringify({
    election_id: election.id,
    candidate_id: election.candidates[index % election.candidates.length],
  });

  classifyVote(http.post(`${BASE_URL}/api/v1/voting/cast/`, body, authHeaders(student.token)));
}
