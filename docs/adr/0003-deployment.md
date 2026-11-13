# ADR-3: Deployment on free tiers

Date: 2026-11-13. Status: accepted.

## Context
The budget is zero. The site needs a public HTTPS URL, PostgreSQL 16 and Redis 7.
The scoring model is also free-only, so nothing here may depend on paid services.

## Decision
Render free tier: one Docker web service, one free Postgres, one free Key Value
(Redis-compatible). The image is the same one docker-compose builds locally.

Render does not run the Docker command through a shell (quoted `sh -c "..."` and
`&&` chains both failed), so migration, idempotent seed and server start live in
`scripts/start.sh`, and the Docker command is `sh scripts/start.sh`. The free tier
has no one-off shell, which is why the seed runs at every start.

Collection and scoring run on the maintainer's machine against the local
database, which is the source of truth. The hosted site serves reviewed results.

## Consequences (provider documentation checked 12 Nov 2026; measurements 13 Nov 2026)
- The free web service spins down after 15 minutes idle. Measured: the first
  request after idle took 73 s (container start, migration and seed); warm
  requests take 0.6-1.3 s. The README tells visitors the first load may take
  about a minute.
- The free Postgres expires 30 days after creation (14-day grace before deletion),
  has no backups, and holds 1 GB. Re-create and re-seed every ~28 days.
- The free Key Value is in-memory only (25 MB); a restart empties the cache,
  which the app already tolerates (ADR-2).
- No hosted worker. Free tier worker availability is unclear in the docs.
- Instance hours are capped at 750 per month and bandwidth counts against the plan.

## Verification on the live site (13 Nov 2026)
- scripts/smoke.py: all 8 checks pass against the public URL.
- `x-cache: HIT` served on /api/policies, so Redis caching works on Render. A live
  MISS-to-HIT transition was not observed because the cache was already warm.
- Admin endpoints return 403 without the token.
- No secrets in git history or in the image (checked env and /app contents).

## Re-seed runbook
1. Take a dump of the local database (see README).
2. Create a new free Postgres, update DATABASE_URL, redeploy.
3. Restore the dump into the new database. Render provides an External Database
   URL for the free Postgres (verified 13 Nov 2026).
4. Run scripts/smoke.py against the live URL.
5. Delete the old database after the new one is confirmed.

## Alternatives
Fly.io and Railway were considered. Their current free-tier terms were not verified
for this decision, so they are not ruled out on evidence.

## Rollback
Redeploy the previous image from the host's deploy history; the database schema
changes are migrations with downgrades.