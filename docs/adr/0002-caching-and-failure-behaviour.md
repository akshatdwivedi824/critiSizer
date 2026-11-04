# ADR-2: Caching and failure behaviour

Status: accepted, 5 Nov 2026

## Context

The policy list scores every policy on every request. Measured on a
development machine (docs/load-test.md), one uncached list costs 43 SQL queries
for 10 policies (3 fixed plus 4 per policy) and about 41 ms, and grows in
direct proportion to the number of policies: about 8,000 queries and 8 s at
2,000 policies. Scores change only when a rating is accepted, a rubric or
evidence changes, or a snapshot is taken, so most reads repeat the same
answer. Redis is already part of the stack, and ratings need an abuse limit.

## Decision

1. **Cache-aside with a 60-second TTL for the policy list.** The handler
   checks Redis, computes on a miss, and stores the result. The key is
   `policies:list:v1:<rubric label>`, so a new rubric version never serves
   old scores. The response carries `X-Cache: HIT` or `MISS`. The policy detail
   page is not cached: it is one policy, and it stays live.
2. **Not write-through.** Scores are derived from many rows (indicators,
   evidence, ratings). A write-through cache would need every write path to
   know which cached values it affects and recompute them. Cache-aside needs
   one invalidation point instead: accepting a rating deletes every key under
   the list prefix after the transaction commits, so a reader cannot re-fill
   the cache with old data. Rejecting a rating changes no score and clears
   nothing.
3. **Fail open.** Every Redis call has a 0.2 s timeout and no retries, and
   catches Redis errors. A cache failure is treated as a miss; a rate-limit
   failure is treated as "allow". Redis is a performance and abuse-protection
   layer, not the source of truth, so its outage must not become a site
   outage.
4. **Rate limit: a fixed window per user, 5 attempts per 60 seconds** on rating
   submissions. A counter key per user is incremented, given an expiry only on
   its first hit, and read back, all in one Redis transaction, so a crash can
   never leave a counter without an expiry. Over the limit, the API returns 429
   with `Retry-After`. Every attempt counts, including ones that end in 404 or
   409: the limit protects request volume, not successes. The limiter runs
   before any database work.

## Alternatives considered

- No cache, optimise the queries: needed eventually, but it does not remove the
  cost of scoring every policy per request.
- Write-through or refresh-ahead: more moving parts for a read pattern this
  simple (see 2).
- Fail closed (reject requests when Redis is down): chosen for systems where
  the limiter is a security boundary and letting traffic through is worse than
  an outage. Here the database's one-rating-per-user rule and the admin
  moderation queue already bound the damage, so open is the better trade.
- Sliding-window or token-bucket limiter: smoother, because a fixed window
  allows a burst of 5 at the end of one minute and 5 at the start of the next.
  Not needed at this scale; revisit if abuse shows up.
- Read the list from the latest weekly snapshot: the better long-term fix
  (one query for all policies), left for later because it also changes how
  fresh a rating's effect appears.

## Consequences

- With the cache on, the list handled 328 req/s (p95 45 ms) on one machine,
  about 80 times the estimated peak.
- A new accepted rating can take up to 60 s to show in the list unless the
  list cache is cleared by an accept. The detail page is always current.
- When Redis is down, every list request pays two timeouts (about 400 ms in
  the measured setup) and logs two tracebacks, so the list went from p50 13 ms
  to 500 ms. A circuit breaker (skip Redis for a few seconds after a failure)
  would remove that cost and is the next improvement.
- After the TTL expires, concurrent requests can all miss and all score at
  once (a stampede). It is harmless at 10 policies and a real problem at 2,000.
  A lock around the recompute, or serving the snapshot, would fix it.
- Rate-limit state lives only in Redis. A Redis restart resets every counter,
  which is acceptable for an abuse limit.