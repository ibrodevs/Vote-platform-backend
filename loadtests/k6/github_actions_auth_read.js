// Authorized distributed authenticated-read load test for GitHub Actions.
//
// 20 shards run in parallel. Aggregate ladder:
//   250 RPS -> 500 RPS -> 750 RPS -> 1000 RPS
//
// Keep each shard <= 50 RPS so the production per-IP Nginx limiter is not
// what we benchmark. Fixtures must contain synthetic students only and are
// supplied at runtime; never commit JWTs to the repository.

import http from 'k6/http';
import { check } from 'k6';
import { Counter, Rate } from 'k6/metrics';
import { authHeaders, indexElectionsByUniversity, loadFixtures, pickEligible } from './lib/config.js';

const BASE_URL = 'https://api.dobush.kg';
const SHARDS = Number(__ENV.SHARDS || '20');
const SHARD = Number(__ENV.SHARD || '1');
const fixtures = loadFixtures();
const byUniversity = indexElectionsByUniversity(fixtures);

function shardShare(total) {
  const base = Math.floor(total / SHARDS);
  const remainder = total % SHARDS;
  return base + (SHARD <= remainder ? 1 : 0);
}

const r250 = shardShare(250);
const r500 = shardShare(500);
const r750 = shardShare(750);
const r1000 = shardShare(1000);

const authFailures = new Rate('auth_read_failed');
const serverErrors = new Rate('server_errors');
const availableCount = new Counter('endpoint_available_requests');
const detailCount = new Counter('endpoint_detail_requests');
const statusCount = new Counter('endpoint_status_requests');

export const options = {
  discardResponseBodies: true,
  scenarios: {
    auth_read_ladder: {
      executor: 'ramping-arrival-rate',
      startRate: r250,
      timeUnit: '1s',
      preAllocatedVUs: 120,
      maxVUs: 500,
      gracefulStop: '10s',
      stages: [
        { target: r250, duration: '30s' },
        { target: r500, duration: '10s' },
        { target: r500, duration: '30s' },
        { target: r750, duration: '10s' },
        { target: r750, duration: '30s' },
        { target: r1000, duration: '10s' },
        { target: r1000, duration: '60s' },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.001'],
    'http_req_duration{expected_response:true}': ['p(95)<300'],
    checks: ['rate>0.999'],
    server_errors: ['rate<0.001'],
    auth_read_failed: ['rate<0.001'],
  },
};

export default function () {
  // Pick a synthetic student and an election from the same university so
  // detail/status measure normal authorized reads rather than rejections.
  const seed = Math.floor(Math.random() * fixtures.students.length);
  const pair = pickEligible(fixtures, byUniversity, seed);
  if (!pair) {
    authFailures.add(true);
    return;
  }

  const { student, election } = pair;
  const opts = authHeaders(student.token);
  opts.timeout = '10s';
  opts.tags = { endpoint: 'auth_read' };

  const roll = Math.random();
  let res;
  if (roll < 0.4) {
    availableCount.add(1);
    res = http.get(`${BASE_URL}/api/v1/elections/available/`, opts);
  } else if (roll < 0.7) {
    detailCount.add(1);
    res = http.get(`${BASE_URL}/api/v1/elections/${election.id}/`, opts);
  } else {
    statusCount.add(1);
    res = http.get(`${BASE_URL}/api/v1/voting/status/${election.id}/`, opts);
  }

  const ok = res.status === 200;
  check(res, { 'HTTP 200': () => ok });
  authFailures.add(!ok);
  serverErrors.add(res.status >= 500);
}
