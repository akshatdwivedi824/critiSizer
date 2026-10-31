# Capacity estimate

Assumptions are stated so they can be challenged. Numbers marked [measured]
come from the seed database; the rest are my planning targets.

## Data volume (year 1)

| Item | Assumption | Row size | Total with indexes (x2) |
|---|---|---|---|
| Policies | 2,000 | [measured] ~1 KB | ~4 MB |
| Indicators | 2,000 x 8 = 16,000 | [measured] ~0.5 KB | ~16 MB |
| Evidence | 16,000 x 1.5 = 24,000 | [measured] ~1 KB | ~48 MB |
| Ratings | 20,000 users x 5 = 100,000 | ~0.1 KB | ~20 MB |
| Weekly snapshots | 2,000 x 52 = 104,000 | ~1 KB | ~208 MB |
| Audit log | 50 changes a day x 365 = 18,250 | ~0.5 KB | ~18 MB |

Total: roughly 0.3 GB in year 1. This fits on one small Postgres instance.

## Traffic

- 1,000,000 page views a month, about 0.4 requests a second on average.
- Peak is perhaps 10x the average, so about 4 requests a second.
- A policy page needs about 4 queries, and each takes a few milliseconds with
  the indexes on the foreign keys. A single Postgres instance serves hundreds of
  these a second.

## Writes

- Ratings: assume 500 a day, so the write rate is negligible.
- Editorial scoring: the real limit. If one editor can review 3 policies a day,
  2,000 policies take over 2 years. The human review queue, not the hardware,
  is the bottleneck.

## What would break first

1. Editorial throughput (see above), solved by sources and process, not servers.
2. The weekly snapshot job, if recomputing every policy gets slow. Fix: run it
   as a background job, and only re-score policies that changed.
3. Hot read paths such as the home page list. Fix: cache in Redis (week 2).
4. Only after that: a read replica for Postgres.

## Decision

One Postgres instance, one API process (several workers), Redis for caching
and rate limits. Scale out only when measured numbers say so.