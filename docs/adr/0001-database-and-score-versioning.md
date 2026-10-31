# ADR 1: PostgreSQL, rubric versions and weekly snapshots

Status: Accepted
Date: 2026-10-31

## Context

critiSizer scores government policies on six negative aspects from sourced
evidence and combines them with public ratings. Three things drive the design:

1. The data is relational: policies have indicators, indicators have evidence,
   users rate policies.
2. Scores must be explainable. Anyone must be able to trace a number back to
   the evidence and the rubric that produced it.
3. The rubric will change. A score computed under one rubric must not silently
   change when the weights change.

## Decision

- Store everything in PostgreSQL 16.
- Enforce rules in the database, not only in code: check constraints on score
  ranges and allowed multipliers, a unique constraint on (user, policy) for
  ratings, a unique constraint on (indicator, content hash) for evidence.
- Keep the scoring engine as a pure function (no database, web or clock).
  The rubric is passed in as an argument and its label travels with the result.
- Version the rubric (`rubric_versions`, `rubric_weights`). Changing weights
  means a new version, never an edit.
- Store a weekly snapshot per (policy, rubric version, week) with the aspect
  scores in a JSONB column, so a past score can be reproduced and compared.
- Keep the verification multiplier on the evidence, and let an indicator use the
  highest multiplier among its evidence.

## Alternatives considered

- **MongoDB or another document store.** Flexible, but the data is relational
  and I want constraints enforced by the database. Rejected.
- **SQLite.** Simple, but no concurrent writers and weaker constraint types.
  Fine for a prototype, not for a service with ratings coming in.
- **Store only the final score.** Smallest, but it cannot be explained or
  recomputed when the rubric changes. Rejected.
- **Edit weights in place.** Simpler, but it silently rewrites history.
  Rejected in favour of versions.

## Consequences

- Good: bad data is rejected at the database even if the code is wrong; scores
  are reproducible; the engine is easy to test (100% coverage).
- Cost: more tables and migrations; a new rubric version needs a deliberate
  re-score and a new snapshot.
- Cost: JSONB aspect scores are not individually constrained by the database,
  so the engine and tests guard their range.
- Revisit if: ratings volume outgrows a single Postgres instance, or we add the
  AI-assisted interpreter (it will need its own ADR for prompt and model
  versioning).