// Distributed public-cache load test for GitHub Actions.
//
// This file is intentionally scoped to the public cached universities endpoint.
// The workflow runs 20 shards in parallel. Per shard the arrival-rate ladder is:
//   500 RPS  -> aggregate 10k RPS
//   1000 RPS -> aggregate 20k RPS
//   2000 RPS -> aggregate 40k RPS
//
// Do not add ?loadtest=1 here: that query intentionally bypasses Nginx cache.

import http from 'k6/http';
import { check } from 'k6';
import { Rate } from 'k6/metrics';

const TARGET_URL = __ENV.TARGET_URL || 'https://api.dobush.kg/api/v1/universities/';
const SHARDS = Number(__ENV.SHARDS || '20');

const rate10k = Math.ceil(10000 / SHARDS);
const rate20k = Math.ceil(20000 / SHARDS);
const rate40k = Math.ceil(40000 / SHARDS);

const cacheNonHit = new Rate('cache_non_hit');

export const options = {
  discardResponseBodies: true,
  scenarios: {
    cached_public_ladder: {
      executor: 'ramping-arrival-rate',
      startRate: rate10k,
      timeUnit: '1s',
      preAllocatedVUs: 800,
      maxVUs: 2500,
      gracefulStop: '10s',
      stages: [
        // 20 shards x 500 = 10k aggregate RPS.
        { target: rate10k, duration: '30s' },

        // Ramp, then hold 20k aggregate RPS.
        { target: rate20k, duration: '10s' },
        { target: rate20k, duration: '30s' },

        // Ramp, then hold 40k aggregate RPS.
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
  const res = http.get(TARGET_URL, {
    headers: {
      'User-Agent': `VotePlatformAuthorizedLoadTest/${__ENV.GITHUB_RUN_ID || 'manual'}`,
    },
    tags: {
      endpoint: 'universities_cached',
    },
    timeout: '10s',
  });

  check(res, {
    'HTTP 200': (r) => r.status === 200,
  });

  const cacheStatus = String(res.headers['X-Cache-Status'] || '').toUpperCase();
  const acceptable = ['HIT', 'STALE', 'UPDATING', 'REVALIDATED'].includes(cacheStatus);
  cacheNonHit.add(!acceptable);
}
