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