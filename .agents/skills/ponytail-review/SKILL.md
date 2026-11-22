---
name: ponytail-review
description: >
  Review a branch, commit, or pull request for correctness, security, scale,
  missing tests, performance, and unnecessary complexity. Read the diff and
  the surrounding code/callers before reporting. Use when asked to review code
  or a PR. Does not modify code.
license: MIT
---

# Ponytail Review — v4.8.4

Review like the engineer who will be paged when the change breaks.

Priority: correctness, security, data integrity, concurrency/load, tests, performance, then lean code.

## Understand first
- Read the complete diff and the code it touches.
- Trace callers, services, data writes, response paths, tests, fixtures, and configuration.
- Identify expected load from project documentation; state assumptions.
- Look beyond changed lines when changed behavior affects other callers.

## Find only concrete issues
- Bugs: wrong result, crash, edge-case failure, broken caller, bad state transition.
- Security: missing trust-boundary checks, auth gaps, unsafe secrets/data handling.
- Data integrity: partial writes, race conditions, incorrect transaction boundaries.
- Scale: process-local state used across workers, unbounded work, N+1 queries, check-then-write races.
- Tests: risky logic without a regression test.
- Complexity: dead code, duplicate helpers, avoidable dependencies, one-implementation abstractions, speculative flexibility.

Every finding must include a concrete input or operating condition and the resulting failure. Do not report style preferences or vague concerns.

## Output
Start with a short description of what the change does. Group findings:
- **Must fix**
- **Should fix**
- **Nice to have**

For each finding include:
1. Title and file/line.
2. What the code does.
3. The exact failure case.
4. The smallest correct fix.
5. Consequence if left unfixed.

Finish with a ship/fix verdict and what could not be checked. This skill is review-only; do not modify code.
