# Election Day Runbook — 200–300k students

This runbook is for the real product scenario, not an artificial 40k durable-vote target.

## Capacity target

For 300,000 eligible students and a 5-hour voting window the average successful vote rate is only ~17 votes/s. The dangerous moment is the synchronized opening burst. The production target is therefore:

- public/cacheable GET: **40,000 RPS** (already proven by distributed load test);
- personalized authenticated API: **5,000 RPS burst target**, then increase only after a clean lower step;
- durable `POST /api/v1/voting/cast/`: **1,000 votes/s initial target**, with 2,000 votes/s as stretch target;
- no lost votes, no double votes, `VoteRecord`/`Ballot` integrity must remain valid;
- p95 target: <300 ms for reads and <500 ms for vote writes under the validated production profile;
- one application-node failure must not corrupt a vote. When a second node/LB is introduced, availability testing is mandatory.

At 1,000 accepted votes/s all 300k voters could be committed in five minutes, so this already gives a very large safety margin over a five-hour election window.

## Why students should log in before 12:00

Open authentication/account access 15–30 minutes before voting starts. The vote button can remain disabled until the election `starts_at`. This spreads password/JWT work over time and avoids combining login + profile + election data + vote into one synchronized second.

Recommended user flow:

1. 11:30–11:55 — students sign in and reach the account page.
2. 11:50 — application principal cache is warmed.
3. 11:55 — public election/candidate caches are warmed by normal GET requests.
4. 12:00 — voting becomes active; clients refresh election state and submit votes.

## T-30 minutes

Do not deploy code, run migrations, import students, rebuild indexes, or generate large exports during the voting window.

```bash
cd /home/deployer/projects/Vote-platform-backend

docker compose -f docker-compose.prod.yml ps
curl -fsS https://api.dobush.kg/health/ready
```

Confirm PostgreSQL, PgBouncer, cache Redis and broker Redis are healthy. If the heavy Celery queue has no required work, stop it for the election window so imports/maintenance cannot compete with vote transactions:

```bash
docker compose -f docker-compose.prod.yml stop celery-heavy
```

Do **not** stop `celery-default` unless the product flow has been checked and notifications/background work are known to be unnecessary.

## T-10 minutes: warm 300k JWT principals

The first authenticated request for a cold student principal otherwise performs a PostgreSQL SELECT. Warming Redis prevents hundreds of thousands of first-request cache misses around 12:00.

```bash
docker compose -f docker-compose.prod.yml exec -T app \
  python manage.py warm_election_day_cache --batch-size 2000 --ttl 1800
```

The command stores only the small authentication principal (id, student code, university id, name, active flag, auth version). It does not cache a password, phone number, email, candidate choice, or Student→Candidate relation.

For an election limited to one university:

```bash
docker compose -f docker-compose.prod.yml exec -T app \
  python manage.py warm_election_day_cache \
  --university-id '<UUID>' --batch-size 2000 --ttl 1800
```

## Public read path

The Nginx election-day config caches only endpoints that are `AllowAny`. It strips accidental frontend `Authorization` headers on those public routes so a global Axios/fetch interceptor cannot force every university/news/candidate request through JWT + Django.

Personalized election detail, `/elections/available/`, profile, vote status and `POST /voting/cast/` are never put in the shared Nginx cache.

The cache is intentionally short (2–60 seconds depending on endpoint) and uses stale-while-updating behavior to prevent a cache-expiry thundering herd.

## NAT-safe throttling

University networks can place thousands of students behind one public IP. Production must never use a single-user IP limit such as 60 requests/s for the authenticated API.

- authenticated action throttles are keyed by `student_id`;
- login/OTP throttles are keyed by a hashed stable account/session identifier, with IP only as fallback;
- Nginx uses only a high coarse edge guard for volumetric abuse.

If a WAF/CDN is added later, the same rule applies: do not configure a low per-IP challenge/rate limit on election-day student traffic without accounting for campus NAT.

## Vote correctness rules — never trade these for speed

The successful vote path remains synchronous and durable:

- PostgreSQL uniqueness is the final one-vote-per-student guard;
- `VoteRecord` and `Ballot` are committed in one transaction;
- the application does not create a Student→Candidate relation;
- the core vote commit is not moved to Celery/Kafka merely to inflate benchmark numbers;
- `fsync`, `full_page_writes` and `synchronous_commit` remain enabled;
- Nginx must not retry `POST /voting/cast/` against a different upstream.

The optimized hot path reads Candidate + Election in one SQL query before the two inserts, reducing one PostgreSQL round trip without weakening these guarantees.

## Host tuning

Apply once, before the load-test window:

```bash
sudo bash scripts/tune_election_host.sh
```

Do not apply random TCP TIME_WAIT/sysctl recipes from the internet. The repository script changes only backlog/file limits, ephemeral port range, low swappiness and conntrack capacity when available.

## Deployment validation

Before exposing the new profile to users:

```bash
docker compose -f docker-compose.prod.yml config >/tmp/vote-compose.rendered.yml

docker compose -f docker-compose.prod.yml exec -T nginx nginx -t

docker compose -f docker-compose.prod.yml exec -T app python manage.py production_check
curl -fsS https://api.dobush.kg/health/ready
```

Then validate progressively. Never jump from a failed level directly to a larger one:

1. personalized auth: 1,000 → 1,250 → 1,500 → 1,750 → 2,000 → 2,500 → 3,000 → 4,000 → 5,000 RPS;
2. vote write using **dedicated synthetic unvoted students/election only**: 100 → 250 → 500 → 750 → 1,000 → 1,500 → 2,000 votes/s;
3. after every vote benchmark run `verify_election_integrity` for that synthetic election;
4. run a double-vote race test separately.

Do not run vote-write benchmarks against real students or a real election.

## What to watch during a test

On the server keep a second SSH session open:

```bash
watch -n 2 'docker stats --no-stream; echo; ss -s'
```

Also watch PostgreSQL/PgBouncer/Redis metrics when available. Stop increasing load when any of these happen: sustained CPU saturation, PgBouncer waiting clients, Redis latency growth, PostgreSQL WAL/checkpoint saturation, p95 outside SLO, request timeouts, dropped k6 iterations, any vote-integrity mismatch, or any unexpected 5xx.

## Rollback

Before deployment keep the previous compose/config commit and the current `.env`. If health or correctness regresses, roll back the application/config commit and restart the affected containers. Do not restore an old PostgreSQL data directory merely to roll back application code.

A failed performance target is not a reason to weaken vote durability. Scale the application/DB tier instead.
