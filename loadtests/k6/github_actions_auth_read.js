// Authorized distributed authenticated-read load test for GitHub Actions.
//
// 20 shards run in parallel. Aggregate ladder:
//   250 RPS -> 500 RPS -> 750 RPS -> 1000 RPS
//
// Keep each shard <= 50 RPS so the production per-IP Nginx limiter is not
// what we benchmark. Fixtures must contain synthetic students only and are
// supplied at runtime; never commit JWTs to the repository.
//
// IMPORTANT: /voting/status/ has StudentActionThrottle=120/min per student.
// With only ~60 synthetic JWTs, making status 30% of a 1000 RPS benchmark
// measures the intentional per-student throttle instead of auth-read capacity.
// Keep status at 5%; the main authenticated workload is /elections/available/.

import http from 'k6/http';
import { check } from 'k6';
import { Counter, Rate } from 'k6/metrics';
import { authHeaders, indexElectionsByUniversity, loadFixtures, pickEligible } from './lib/config.js';

const BASE_URL = 'https://api.dobush.kg';
const SHARDS = Number(__ENV.SHARDS || '20');
const SHARD = Number(__ENV.SHARD || '1');
const fixtures = __ENV.FIXTURES_JSON ? JSON.parse(__ENV.FIXTURES_JSON) : loadFixtures();
const byUniversity = indexElectionsByUniversity(fixtures);

if (!fixtures.students || fixtures.students.length < 20) {
  throw new Error('Need at least 20 synthetic student fixtures');
}
if (!fixtures.elections || fixtures.elections.length === 0) {
  throw new Error('Need at least one active synthetic election fixture');
}
if (!fixtures.students.every((s) => String(s.code || '').startsWith('synthetic-'))) {
  throw new Error('Refusing non-synthetic student fixtures');
}

function shardShare(total) {
  const base = Math.floor(total / SHARDS);
  const remainder = total % SHARDS;
  return base + (SHARD <= remainder ? 1 : 0);
}

const r250 = shardShare(250);
const r500 = shardShare(500);
const r750 = shardShare(750);
const r1000 = shardShare(1000);

const responseFailures = new Rate('auth_read_failed');
const serverErrors = new Rate('server_errors');
const availableCount = new Counter('endpoint_available_requests');
const detailCount = new Counter('endpoint_detail_requests');
const statusCount = new Counter('endpoint_status_requests');
const availableFailed = new Counter('endpoint_available_failed');
const detailFailed = new Counter('endpoint_detail_failed');
const statusFailed = new Counter('endpoint_status_failed');
const status401 = new Counter('status_401');
const status403 = new Counter('status_403');
const status404 = new Counter('status_404');
const status429 = new Counter('status_429');
const other4xx = new Counter('status_other_4xx');

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

function recordStatus(res) {
  if (res.status === 401) status401.add(1);
  else if (res.status === 403) status403.add(1);
  else if (res.status === 404) status404.add(1);
  else if (res.status === 429) status429.add(1);
  else if (res.status >= 400 && res.status < 500) other4xx.add(1);
}

export default function () {
  const seed = Math.floor(Math.random() * fixtures.students.length);
  const pair = pickEligible(fixtures, byUniversity, seed);
  if (!pair) {
    responseFailures.add(true);
    return;
  }

  const { student, election } = pair;
  const opts = authHeaders(student.token);
  opts.timeout = '10s';
  opts.tags = { endpoint: 'auth_read' };

  const roll = Math.random();
  let res;
  let endpoint;

  if (roll < 0.80) {
    endpoint = 'available';
    availableCount.add(1);
    res = http.get(`${BASE_URL}/api/v1/elections/available/`, opts);
  } else if (roll < 0.95) {
    endpoint = 'detail';
    detailCount.add(1);
    res = http.get(`${BASE_URL}/api/v1/elections/${election.id}/`, opts);
  } else {
    endpoint = 'status';
    statusCount.add(1);
    res = http.get(`${BASE_URL}/api/v1/voting/status/${election.id}/`, opts);
  }

  const ok = res.status === 200;
  if (!ok) {
    if (endpoint === 'available') availableFailed.add(1);
    else if (endpoint === 'detail') detailFailed.add(1);
    else statusFailed.add(1);
    recordStatus(res);
  }

  check(res, { 'HTTP 200': () => ok });
  responseFailures.add(!ok);
  serverErrors.add(res.status >= 500);
}
