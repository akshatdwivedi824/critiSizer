# critiSizer log

## Day 1 to 5
(for each day: what I built, what went wrong, one thing I learned)

## Day 6: engine tests and seed data
- What I built:
- What went wrong:
- Review question: the loader skips any policy whose slug already exists.
  What happens if I correct a score in the YAML and re-run, and how would I
  change the loader?
  My answer:

## Decisions
- Multiplier lives on evidence, not on the indicator, because:
- An indicator's multiplier is the highest among its evidence, because:
- Rounding: 41.25 shows as 41.2 because Decimal rounds exact ties to even.
  I will decide a rule before launch (round half up) because:

## Day 7: ADR, capacity, gate 1
- Capacity review question: why can the system stay on one database at this
  size, and which of the four bottlenecks would I tackle first if traffic grew
  50 times?
  My answer:


## Day 10 - Wed 4 Nov - Redis cache and rate limit

Built: cache-aside for GET /api/policies (key policies:list:v1:<rubric label>,
60 s TTL, X-Cache HIT/MISS header). Per-user fixed-window rate limit on rating
attempts (5 per 60 s, 429 with Retry-After). Both fail open. Tests use Redis
database 15, cleared before and after every test. CI now has a Redis service.
Tests: 66 passing.

Measured: list with Redis up (HIT) [__] s; list with Redis stopped [__] s.

Decisions:
- Cache the list only, not the detail page. The detail page stays live.
- Redis errors never reach the user: a cache failure is a miss, a limiter
  failure is "allow".
- The limiter counts every attempt, including 404 and 409, so it limits
  request volume, not successes.
- INCR, EXPIRE NX and TTL run in one transaction, so a counter can never be
  left without an expiry.
- redis-py retries switched off: a retry costs more than a miss.

Found: two "Redis down" tests took 64 s of a 71 s run because a refused
connection plus redis-py retries is slow on Windows. Fixed with a fake dead
client in tests and Retry(NoBackoff(), 0) in the app. Suite now 7.7 s.

Known limits:
- A new accepted rating can take up to 60 s to show in the list (TTL only,
  no invalidation). The detail page is live.
- Fixed window: a user can make 5 attempts at the end of one minute and 5 at
  the start of the next. A sliding window would fix that; not needed yet.
- Rate limit is per user only, so sign-up and login are not limited yet.
- On a cache miss the list still scores every policy (the N+1 pattern).
  Day 13 load test will show how bad.

Review answer: why does the limiter fail open instead of blocking when Redis
is down? [Your answer in your own words. Hint: what is Redis here, and what
would a block do to real users?]

## Day 11 decisions
- A week is the date of the Monday of its ISO week, from one helper function.
- Re-run rule: an existing snapshot for the same (policy, rubric version, week)
  is left alone. `--replace` overwrites it.
- Aspect scores are stored in JSONB as strings of the exact Decimal values,
  not floats, so a snapshot re-reads without precision loss.
- Every snapshot stores its rubric version id.
- A policy that fails scoring is logged and skipped. One bad policy does not
  stop the others.

## Day 13 - Fri 6 Nov - Load test

Built: loadtest/locustfile.py (80% list, 20% detail), docs/load-test.md,
"Measured" section in docs/capacity.md, scripts/count_queries.py.

Results (4 workers, 10 policies, one machine):
- Cache on, 50 users: 328 req/s, p95 45 ms, 0 failures (limited by the test users).
- Redis stopped, 50 users: 87 req/s, p95 580 ms.
- Redis stopped, 200 users: 93 req/s, p95 3.2 s, saturated, 0 failures.
- One uncached list = 43 queries (3 + 4 per policy), 41 ms. At 2,000 policies:
  about 8,003 queries, about 8.3 s.

Findings:
- A Redis outage turns a 13 ms list into a 500 ms list (two 0.2 s timeouts).
  Fix to build later: a circuit breaker.
- Every TTL expiry can cause a stampede once scoring is slow.
- The estimate (4 req/s) is met 80x over with the cache and 20x over without
  it at 10 policies, but not at 2,000 policies without the cache.

Review answer: which part of the system limits throughput first, and what is
the fix? [Your answer, in your own words: the per-request scoring of every
policy (queries grow with policies). Fixes: the cache now, reading the latest
snapshot later.]

   ## Day 14 - Week 2 wrap-up

   Built: README with screenshot, architecture diagram, run steps and endpoint
   table; scripts/gate2.py (19 checks, all PASS); ADR-2 (caching and failure
   behaviour); cache helper tests. Coverage 92% before, about 94% after.
   Tests: 98 passing. Tagged v0.2.0.

   Decisions: Gate 2 reads routes from the OpenAPI schema, because this FastAPI
   version nests included routers and app.routes does not list them.

   Week 3 bullets:
   - The load test says: scoring every policy per request is the limit; serve
     the list from the latest snapshot, add a circuit breaker for Redis outages,
     and protect against a stampede when the TTL expires.
   - A stranger would not understand from the README: [your answer, for example
     what "verification multiplier" means, or how the people's rating is gated].
   - I want to learn next: [your answer].
## Day 16 (Mon 9 Nov)
- Frozen scoring method + prompt_v1, scorer interface, quote verifier, FakeScorer, draft storage (drafts never count until approved).
- Found and fixed: partial aspect coverage crashed scoring. Aspects with no indicators now count 0; indicators with only allegations are still rejected.
- 132 tests passing.

