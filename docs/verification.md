# Verification record — repository-aware import P0

Date: 2026-10-15. Baseline: `c440f915c7e24436f904a6ffff39a72859cd168f`.
This verification record was captured before commit/push. No production repository operation was performed.

| Check | Actual result |
| --- | --- |
| Python 3.12.14, `python -m unittest discover -s tests -v` | 99 tests passed |
| Python 3.11.17, same suite | 99 tests passed |
| Node.js 24.19.0 EA API fixtures | Included in those suites; no failed/skipped tests |
| Node syntax checks for governed importer and bundled exporter | Passed |
| Python compilation of changed application modules | Passed |
| Streamlit fresh startup, `127.0.0.1:18506/_stcore/health` | HTTP 200, `ok`; temporary server then stopped |
| `git diff --check` | Passed |
| Real Sparx EA / BPMN or ArchiMate MDG / Wine | **NOT RUN — runtime unavailable** |
| Real local `.qea` acceptance | **NOT RUN — release blocker** |
| Production server connection or mutation | Not attempted |

The original 53 test scenarios were retained, with UI expectations updated for the new controls. Historical legacy generator-core execution tests are explicitly marked as such and call the private legacy helper; they are not evidence for governed public safety. New tests exercise the public Generic/BPMN paths, shared planner/runtime, actual Streamlit review/approval flow, and local-only TRM guard. All input fixtures are synthetic.

The strict Node fixture rejects unknown Repository methods, unsupported element/connector types, unsupported qualified connector stereotypes/base types, missing endpoints, malformed diagram placement, and forbidden mutations. `VALIDATE_ONLY` and failed preflight are tested with zero mutator calls; a fixture can reject every write or fail Update to test the created-object ledger. This fixture is deliberately limited and does not implement or certify EA.

Safety scenarios include canonical Actor/ConnectorGUID reuse across diagrams and repeated imports; stale/missing/wrong GUIDs; duplicate names and conflicting source bindings; OPCO/scope/identity mismatch; Pool/Lane parent constraints; cross-Pool/subprocess Sequence Flow rejection and valid Message Flow reuse; Data Association restrictions; conservative ArchiMate type rules and Access mode conflicts; role/tag/connector and role-note fingerprint changes; unapproved production relationships; approval invalidation; dangling source edges; a master appearing after export; duplicate unnamed proposals requiring review; and partial-write reporting without a rollback claim.

Some legacy Streamlit calls emit `use_container_width` deprecation notices. Those notices do not change the pass results. Rendering and native MDG behavior remain outside the stub's scope.

Follow [manual acceptance on macOS/Wine](manual-acceptance-wine.md) using synthetic local data. Any failed repository-safety or relationship-integrity case blocks production release. Native MDG base types, tagged-property names/values, physical ownership and richer relationship semantics must be checked against the installed EA version before release.
