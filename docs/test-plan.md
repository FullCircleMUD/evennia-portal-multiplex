# Test plan

Every test case the library commits to covering, and the test function that covers it. The library is
built test-first: cases are agreed here, tests are written against them, then the implementation is
written to pass. The **Test function** column is the auditable trail — it is filled in as each test is
written, so an empty cell means the case is agreed but not yet covered.

Case IDs are stable and referenceable. Do not renumber; retire an ID rather than reuse it. Every test
function carries its case ID as its docstring, so the trail reads in both directions.

All test functions live in `src/evennia_portal_multiplex/tests.py`.

No cases yet. Behaviour is agreed here first, before any test or code — see
[test-first-process.md](../../../design/test-first-process.md). The structure below is the shape each
section takes as it fills in.

| Prefix | Covers |
|---|---|
|  |  |

## Fixtures

The fake objects the suite needs, named and purposed.

| Fixture | Purpose |
|---|---|
|  |  |

## Cases

One section per function or surface, each with its own prefix and its own table.

| ID | Case | Test function |
|---|---|---|
|  |  |  |

## Open decisions

Open questions land here as `[TBD — needs discussion: …]` against the specific case they block,
collected in this section. A case with open behaviour is still listed, but it does not pass.
