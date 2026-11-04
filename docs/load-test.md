# Load test, 4 Nov 2026

Tool: locust 2.47, headless. Scenario (`loadtest/locustfile.py`): 80% GET
/api/policies, 20% GET /api/policies/{slug} over the real slugs; each user
pauses 50-200 ms between requests. Server: `uvicorn --workers 4`, no reload.
Data: 10 policies. Everything (locust, server, Postgres, Redis) ran on one
Windows development machine, so numbers are indicative, not production figures.
A 10-second warm-up run before each setup was ignored.

## Results

| Run | Scenario | Users | Workers | Redis | req/s | p50 | p95 | p99 | Failures |
|---|---|---|---|---|---|---|---|---|---|
| 1 | cache on | 50 | 4 | running | 328.3 | 15 ms | 45 ms | 100 ms | 0 |
| 2 | cache off (Redis stopped) | 50 | 4 | stopped | 86.9 | 500 ms | 580 ms | 660 ms | 0 |
| 3 | cache off, heavy | 200 | 4 | stopped | 92.8 | 1,400 ms | 3,200 ms | 3,800 ms | 0 |

Per endpoint (req/s / p50 / p95 / p99):

| Endpoint | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| GET /api/policies | 262.5 / 13 / 39 / 86 | 70.0 / 500 / 590 / 670 | 74.6 / 1,500 / 3,300 / 3,800 |
| GET /api/policies/{slug} | 65.8 / 23 / 62 / 150 | 16.9 / 24 / 53 / 90 | 18.1 / 970 / 3,000 / 3,300 |

## Reading the results

- Run 1 is limited by the simulated users, not the server: 50 users with a
  50-200 ms pause can send at most about 345 req/s, and the run reached 328.
  The cache-on figure is a lower bound.
- Run 2 measures a Redis outage, not "no cache": the list endpoint waits out
  two 0.2 s Redis timeouts (about 400 ms) before it scores every policy.
  List p50 went from 13 ms to 500 ms; the detail endpoint, which does not use
  Redis, was unchanged (23 ms to 24 ms).
- Run 3: throughput stayed at about 90 req/s while users went from 50 to 200,
  and latency rose from 0.5 s to 1.4 s (p50) and 3.2 s (p95). That is the
  saturation point of the cache-off path. No request failed, even at a 5 s
  worst case: it degrades slowly instead of breaking.
- The outage path also logs two full tracebacks per request, which adds cost
  in this setup.

## What this means

- Cache on: about 80 times the 4 req/s peak estimated in capacity.md.
- Cache off: about 20 times that estimate at 10 policies, but throughput falls
  as the number of policies grows (see capacity.md, "Measured").
- Fix for the outage path: a circuit breaker (skip Redis for a few seconds
  after a failure), so an outage costs the scoring time only, not the timeouts.