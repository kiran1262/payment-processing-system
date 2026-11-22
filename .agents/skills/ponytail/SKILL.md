---
name: ponytail
description: >
  Forces the smallest solution that fully works. Use for coding, bug fixing,
  refactoring, code review, dependency choices, and reuse-first implementation.
  Apply YAGNI, inspect existing callers and data flow, reuse existing helpers,
  prefer standard library/native features/already-installed dependencies, and
  keep the diff minimal without weakening correctness, security, validation,
  accessibility, or tests. Supports lite, full, and ultra modes.
argument-hint: "[lite|full|ultra]"
license: MIT
---

# Ponytail — v4.8.4

Be efficient, not careless. The best code is the code never written.

## Before changing code
1. Read the task and every touched code path.
2. Trace callers, tests, fixtures, configuration, and data flow end to end.
3. Identify what can break, leak, or be lost.
4. Search the repository for an existing helper or established pattern before adding one.

## Minimal implementation ladder
Stop at the first option that fully solves the problem:
1. Does this need to exist? Skip speculative work (YAGNI).
2. Does this codebase already have a helper, service, type, or pattern? Reuse it.
3. Can the standard library do it?
4. Can a native platform or database feature do it?
5. Can an already-installed dependency do it?
6. Can the intent be expressed clearly in one line?
7. Otherwise, implement the smallest complete solution.

## Non-negotiable rules
- Fix root causes in shared code, not symptoms in individual callers.
- Finish all required callers, tests, fixtures, and configuration changes.
- Do not add speculative abstractions, wrappers, factories, options, or dependencies.
- Preserve validation and error handling when moving or merging code.
- Prefer the simplest edge-case-correct implementation.
- Add a small runnable test for non-trivial logic, especially money, security, parsing, and state changes.
- Never remove trust-boundary validation, security, transaction safety, data-loss protection, accessibility, or explicitly requested behavior.
- Mark a deliberate shortcut with its limit and upgrade condition: `ponytail: <limit>, <when to upgrade>`.

## Modes
- **lite:** implement the request and mention the smaller alternative.
- **full:** enforce the ladder; this is the default.
- **ultra:** challenge unnecessary requirements and prefer deletion.

Read fully before deciding to write less. A short diff in the wrong place is still a bug.
