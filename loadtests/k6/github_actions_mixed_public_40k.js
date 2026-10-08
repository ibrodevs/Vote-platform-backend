// Authorized distributed mixed public-cache load test for GitHub Actions.
//
// 20 shards run in parallel. Per shard:
//   500 RPS  -> aggregate 10k RPS
//   1000 RPS -> aggregate 20k RPS
//   2000 RPS -> aggregate 40k RPS
//
// The four public endpoints are selected uniformly so each cache key and TTL
// is exercised under sustained load. Do not add query strings: the production
// Nginx config intentionally bypasses cache when query args are present.

import http from 'k6/http';
import { check } from 'k6';
import { Rate, Counter } from 'k6/metrics';

const BASE_URL = 'https://api.dobush.kg';
const SHARDS = Number(__ENV.SHARDS || '20');

const rate10k = Math.ceil(10000 / SHARDS);
const rate20k = Math.ceil(20000 / SHARDS);
const rate40k = Math.ceil(40000 / SHARDS);

const ENDPOINTS = [
  { key: 'universities', path: '/api/v1/universities/' },
  { key: 'elections_recent', path: '/api/v1/elections/recent/' },
  { key: 'faqs', path: '/api/v1/faqs/' },
  { key: 'news', path: '/api/v1/news/' },
];

const cacheNonHit = new Rate('cache_non_hit');
const endpointCounts = Object.fromEntries(
  ENDPOINTS.map((e) => [e.key, new Counter(`endpoint_${e.key}_requests`)])
);
const endpointFailures = Object.fromEntries(
  ENDPOINTS.map((e) => [e.key, new Rate(`endpoint_${e.key}_failed`)])
);
const endpointCacheBad = Object.fromEntries(
  ENDPOINTS.map((e) => [e.key, new Rate(`endpoint_${e.key}_cache_non_hit`)])
);

export const options = {
  discardResponseBodies: true,
  scenarios: {
    mixed_public_ladder: {
      executor: 'ramping-arrival-rate',
      startRate: rate10k,
      timeUnit: '1s',
      preAllocatedVUs: 800,
      maxVUs: 2500,
      gracefulStop: '10s',
      stages: [
        { target: rate10k, duration: '30s' },
        { target: rate20k, duration: '10s' },
        { target: rate20k, duration: '30s' },
        { target: rate40k, duration: '10s' },
        { target: rate40k, duration: '60s' },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.001'],
    'http_req_duration{expected_response:true}': ['p(95)<500'],
    checks: ['rate>0.999'],
    cache_non_hit: ['rate<0.01'],
  },
};

export default function () {
  const endpoint = ENDPOINTS[Math.floor(Math.random() * ENDPOINTS.length)];
  const res = http.get(`${BASE_URL}${endpoint.path}`, {
    headers: {
      'User-Agent': `VotePlatformAuthorizedMixedLoadTest/${__ENV.GITHUB_RUN_ID || 'manual'}`,
    },
    tags: {
      endpoint: endpoint.key,
    },
    timeout: '10s',
  });

  const ok = res.status === 200;
  check(res, {
    'HTTP 200': () => ok,
  });

  const cacheStatus = String(res.headers['X-Cache-Status'] || '').toUpperCase();
  const acceptableCache = ['HIT', 'STALE', 'UPDATING', 'REVALIDATED'].includes(cacheStatus);

  endpointCounts[endpoint.key].add(1);
  endpointFailures[endpoint.key].add(!ok);
  endpointCacheBad[endpoint.key].add(!acceptableCache);
  cacheNonHit.add(!acceptableCache);
}
