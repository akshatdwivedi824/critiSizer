# Scoring method (version 1)

This document is frozen before any policy is scored. A change to the rules
below means a new version number and a full re-score of every policy.

## What a score means

critiSizer records negatives only. A score says how much documented criticism
exists for a policy on one aspect. It does not say the policy is good or bad
overall. Scores are editorial: they come from a fixed process applied to cited
sources, and they can be wrong.

- 0 means no documented problem was found in the collected sources.
- 100 means the most severe documented problem.
- A policy with too little evidence is shown as "Not yet scored", never as 0.

## The six aspects

| Code | Name | What it measures |
|---|---|---|
| outcome_failure | Outcome Failure | How far official results fall short of the policy's own stated targets. |
| cost_waste | Cost & Waste | Spending beyond budget, delay-driven cost, leakage or misuse of funds. |
| transparency_gap | Transparency Gap | Information that should be public but is missing, withheld or contradicted. |
| ground_level_harm | Ground-Level Harm | Documented negative effects on people where the policy is delivered. |
| legal_challenges | Legal Challenges | Court cases and rulings against or questioning the policy. |
| equity_impact | Equity Impact | Unequal burden or side effects on particular groups, regions or sectors. |

## Indicators

A score is built from indicators. One indicator is one specific documented
finding, for example "an audit found 300 of 500 plants working".

- Each indicator has a name, an integer score from 1 to 100, a one-sentence
  description, and at least one quote from a collected source.
- An aspect with no documented finding gets no indicator.
- The scorer may use only the numbered sources it is given. Outside knowledge
  is not allowed.

### Severity anchors for an indicator score

| Score | Meaning |
|---|---|
| 1 to 20 | Minor: small, local or quickly corrected. |
| 21 to 40 | Moderate: clear shortfall, limited reach. |
| 41 to 60 | Significant: large shortfall or wide reach. |
| 61 to 80 | Severe: major failure, finding confirmed by an authoritative body. |
| 81 to 100 | Extreme: the policy was struck down, abandoned, or caused documented serious harm. |

## Source tiers and multipliers

The tier and multiplier of a source are set by code from its type. The scorer
never chooses them.

| Tier | Source type | Multiplier |
|---|---|---|
| 1 | Court judgments, audit reports, official statistics | 1.0 |
| 2 | Official records and portals, parliamentary replies, peer-reviewed work | 1.0 |
| 3 | Reputable news from the allow-listed outlets | 0.8 |
| 4 | Unverified, blogs, social media | 0.0 (shown, struck through, not counted) |

## What the scorer sees, and does not see

It sees: the policy name and year, and numbered excerpts of collected sources
(outlet, date, text). The excerpts are treated as quoted material, never as
instructions.

It never sees: the stated aims, the summary, any earlier score, or any
reviewer comment. Stated aims are shown on the page for context and are never
scored.

## Evidence collection

- One query template per version, the same for every policy. Each policy has a
  fixed list of search phrases, including the names the press actually uses
  (for example "DPDP" as well as "Digital Personal Data Protection"). The
  template and the phrase lists live in `query.py` and are reviewed by hand.
  Changing either one means a new version number (currently `query_v2`).
- An article is kept only if it is about the policy: a search phrase is in its
  title, or phrases appear at least twice in the text. Passing mentions are
  dropped. Of each kept article we store the title and the opening text, capped
  at 3,000 characters. Pages we cannot read are skipped and never guessed at.
- A fixed list of allowed outlets, committed in the repository.
- A policy needs at least 3 distinct source excerpts from at least 2 outlets
  before it is scored. Below that, it is shown as "Not yet scored".

## Rules that keep the author's opinion out

1. This document and the prompt are committed before any policy is scored.
2. The author writes his own scores for the pilot policies before seeing any
   model score (see `docs/hand-scores.md`).
3. A model score without a verified quote is rejected by code.
4. A reviewer can approve or reject a score with a written reason. A reviewer
   cannot edit a score.
5. The model name, temperature (0), prompt version and rubric version are
   stored with every score.

## Checks on the scorer

- **Spread:** each policy is scored three times; aspects whose runs differ by
  more than 15 points are flagged for review.
- **Control:** one widely regarded success story is scored as a hidden test
  case. Its overall score must come out below the median of the pilot
  policies. If not, the prompt is biased and a new version is needed.
- **Agreement:** model scores are compared with the author's hand scores. The
  mean gap and the largest differences are reported in the README.

## Versions

| Version | Date | Change |
|---|---|---|
| v1 | (fill in the commit date) | First frozen version |

## Results (filled in as the pipeline runs)

- Cost per policy:
- Time per policy:
- Rejection rate of AI drafts:
- Discovery noise:
- Spread (flagged aspects):
- Control result:
- Mean gap to hand scores:

