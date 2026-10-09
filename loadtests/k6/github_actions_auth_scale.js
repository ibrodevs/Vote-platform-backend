// Authorized distributed JWT-authenticated scale benchmark.
//
// This deliberately uses a public read endpoint WITH Authorization and a query
// string. DRF still runs CombinedJWTAuthentication, while Nginx must bypass the
// public response cache. That lets us measure the JWT + Redis principal hot path
// without measuring the per-student action throttle of protected endpoints.
//
// Find the ceiling progressively. Do not jump over a failed target.

import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';
import { Counter, Rate, Trend } from 'k6/metrics';
import { authHeaders, loadFixtures } from './lib/config.js';

const BASE_URL = 'https://api.dobush.kg';
const URL = `${BASE_URL}/api/v1/universities/?auth_load=1`;
const SHARDS = Number(__ENV.SHARDS || '20');
const SHARD = Number(__ENV.SHARD || '1');
const TARGET_TOTAL = Number(__ENV.TARGET_RPS || '1500');
const TEST_START_EPOCH = Number(__ENV.TEST_START_EPOCH || '0');
const fixtures = __ENV.FIXTURES_JSON ? JSON.parse(__ENV.FIXTURES_JSON) : loadFixtures();
const allowedTargets = [1000, 1250, 1500, 1750, 2000, 2500, 3000, 4000, 5000, 10000, 20000, 40000];

if (!allowedTargets.includes(TARGET_TOTAL)) {
  throw new Error(`TARGET_RPS must be one of ${allowedTargets.join(', ')}`);
}
if (!fixtures.students || fixtures.students.length < 20) {
  throw new Error('Need at least 20 synthetic student fixtures');
}
if (!fixtures.students.every((s) => String(s.code || '').startsWith('synthetic-'))) {
  throw new Error('Refusing non-synthetic student fixtures');
}

function shardShare(total) {
  const base = Math.floor(total / SHARDS);
  const remainder = total % SHARDS;
  return base + (SHARD <= remainder ? 1 : 0);
}

const target = shardShare(TARGET_TOTAL);
const start = Math.max(1, Math.floor(target * 0.20));

const responseFailed = new Rate('auth_scale_response_failed');
const serverErrors = new Rate('server_errors');
const cacheServed = new Rate('cache_served');
const holdRequests = new Counter('hold_requests');
const holdFailed = new Rate('hold_failed');
const holdDuration = new Trend('hold_duration', true);
const status0 = new Counter('status_0_timeout_or_network');
const status401 = new Counter('status_401');
const status403 = new Counter('status_403');
const status429 = new Counter('status_429');
const status5xx = new Counter('status_5xx');

export const options = {
  discardResponseBodies: true,
  scenarios: {
    auth_scale: {
      executor: 'ramping-arrival-rate',
      startRate: start,
      timeUnit: '1s',
      preAllocatedVUs: 600,
      maxVUs: 4000,
      gracefulStop: '5s',
      stages: [
        { target, duration: '15s' },
        { target, duration: '60s' },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.001'],
    checks: ['rate>0.999'],
    cache_served: ['rate<0.001'],
    auth_scale_response_failed: [
      { threshold: 'rate<0.02', abortOnFail: true, delayAbortEval: '15s' },
    ],
    server_errors: [
      { threshold: 'rate<0.02', abortOnFail: true, delayAbortEval: '15s' },
    ],
    'http_req_duration{expected_response:true}': [
      { threshold: 'p(95)<2000', abortOnFail: true, delayAbortEval: '15s' },
    ],
  },
};

function isCacheServed(res) {
  const v = String(res.headers['X-Cache-Status'] || '').toUpperCase();
  return ['HIT', 'STALE', 'UPDATING', 'REVALIDATED'].includes(v);
}

function optionsFor(token) {
  const opts = authHeaders(token);
  opts.timeout = '5s';
  opts.tags = { endpoint: 'jwt_auth_scale' };
  opts.headers['User-Agent'] = 'VotePlatformAuthorizedAuthScale';
  return opts;
}

export function setup() {
  const token = fixtures.students[0].token;
  const good = http.get(URL, optionsFor(token));
  if (good.status !== 200) {
    throw new Error(`Preflight valid JWT expected 200, got ${good.status}`);
  }
  if (isCacheServed(good)) {
    throw new Error(`Preflight must bypass Nginx cache, got X-Cache-Status=${good.headers['X-Cache-Status']}`);
  }

  const last = token.slice(-1);
  const badToken = `${token.slice(0, -1)}${last === 'a' ? 'b' : 'a'}`;
  const bad = http.get(URL, optionsFor(badToken));
  if (bad.status !== 401 && bad.status !== 403) {
    throw new Error(`Auth preflight failed: tampered JWT returned ${bad.status}, expected 401/403`);
  }

  return { ok: true };
}

export default function () {
  const idx = exec.scenario.iterationInTest % fixtures.students.length;
  const student = fixtures.students[idx];
  const res = http.get(URL, optionsFor(student.token));

  const ok = res.status === 200;
  const served = isCacheServed(res);
  responseFailed.add(!ok);
  serverErrors.add(res.status >= 500);
  cacheServed.add(served);

  if (res.status === 0) status0.add(1);
  else if (res.status === 401) status401.add(1);
  else if (res.status === 403) status403.add(1);
  else if (res.status === 429) status429.add(1);
  else if (res.status >= 500) status5xx.add(1);

  const elapsedMs = TEST_START_EPOCH > 0 ? Date.now() - TEST_START_EPOCH * 1000 : 0;
  if (elapsedMs >= 15000) {
    holdRequests.add(1);
    holdFailed.add(!ok);
    holdDuration.add(res.timings.duration);
  }

  check(res, {
    'HTTP 200': () => ok,
    'cache bypassed': () => !served,
  });
}