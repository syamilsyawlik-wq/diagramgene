# Direct QEA verification record

Date: 2026-10-22. Working implementation based on `787dfcc9bb32e2bff1f6ebf32d963eae34a0d0e8`.
No customer database, catalogue, credentials, production access or repository writes
were used. Writable SQL appears only in synthetic test-fixture construction.

| Check executed | Actual result |
| --- | --- |
| Python 3.12.14, `.venv/bin/python -m unittest discover -s tests -q` | **122 tests passed**, 11.554 seconds |
| Python 3.11.17, same test suite | **122 tests passed**, 11.562 seconds |
| Node.js strict EA Automation API fixture | Included in the passing suite; direct QEA catalogue reuses Actor/Connector GUIDs across two diagrams and repeated runs |
| `node --check runtime/importer.js` | Passed |
| Python compilation of modified/new application modules | Passed |
| Final macOS extension-loading guard, targeted `test_qea.py` rerun on Python 3.12 | **22 tests passed**, 1.274 seconds |
| Fresh Streamlit startup, `127.0.0.1:18508/_stcore/health` | HTTP 200, `ok`; temporary server stopped |
| `git diff --check` | Passed |
| Real EA-created `.qea`, macOS, Wine, native BPMN/ArchiMate MDGs | **NOT RUN — environment unavailable; production release blocker** |
| `.qeax`, live PCS/server access, concurrent WAL reading | Unsupported/not attempted |

The original 97-test suite is retained. One former UI expectation was changed:
a plain Note named Manager can receive a type suggestion, but its name cannot
automatically bind the Actor GUID. Existing UI regressions deliberately select
the advanced snapshot route; separate AppTests exercise the default direct-QEA
path, analysis, scope/output selection, inspector, Actor proposal, stale detection,
identity-review reset and restricted backend access.

New SQLite tests cover enumeration and normalization; explicit read-only SQL
denials; missing/corrupt/locked/unsupported files; column introspection; journal,
WAL and symlink-root rejection; parameterized filters; extraction/time/memory
bounds; cycles/missing endpoints; qualified stereotypes; unknown MDG/xref/role
metadata; private memo/Notes hashing; cache hit/refresh/scope/tamper handling;
mtime-independent drift detection; uploaded provenance trust boundaries; Actor
NEW/REUSE/review proposals; same-name ambiguity; BPMN parent/type/tag handling;
local identity acknowledgement and production rejection. Incomplete connector
metadata cannot silently become a new-relationship proposal even when a different
meaning is requested for the same endpoint pair.

Existing tests continue covering draw.io and embedded formats, Visio, UML/ArchiMate,
BPMN and TRM; wrong endpoint/type/stereotype/repository rejection; cross-Pool
Sequence Flow rejection and valid Message Flow; source identity collisions;
unapproved production connector creation; preflight zero writes and partial-write
ledgers. Native API stub success is not native integration proof.

## Test H: measured synthetic repository benchmark

Command actually executed on Python 3.12.14 / SQLite 3.53.1 /
Linux 6.18.55 x86_64 glibc 2.41:

```bash
.venv/bin/python tests/benchmark_qea.py --objects 20000
```

Fixture: **102 packages, 20,002 objects, 101 diagrams, 20,001 connectors**,
20,001 diagram placements, **6.96 MiB** database. Indexed synthetic tables; values
are short and mostly default. This is not a large confidential EA database and
does not model every native table, long Notes, custom MDG, or disk configuration.

| Measured operation | Seconds | Peak Python allocations (MiB) |
| --- | ---: | ---: |
| Repository overview/schema/counts | 0.0043 | 0.03 |
| Browse 50 scoped elements | 0.0037 | 0.07 |
| Expanded scoped catalogue extraction + normalization + cache write | 14.4846 | 247.74 |
| Cold derived cache load + validation | 5.7109 | 138.50 |

`tracemalloc` measures each operation separately and adds overhead; figures exclude
SQLite native heap, process RSS and fixture construction. Cache-hit and unchanged
source SHA-256 assertions passed. A dedicated unit test also verifies that a cache
hit never opens SQLite. No raw repository copy is created by the application.

The benchmark explicitly expands extraction limits to cover the entire synthetic
catalogue. Default UI extraction is limited to 10,000 elements; larger scopes are
rejected with a request for a smaller package. Derived metadata still has a
material memory cost. Session reuse avoids reparsing this catalogue every UI rerun;
the disk cache is not an instant/zero-allocation operation. Treat these measurements
as a baseline for future optimization, not a production performance guarantee.

## Acceptance status

Code audit, reader, adapter, UI, proposal and governed integration phases have
working implementations and automated verification. Native schema/metamodel
qualification remains **unfinished**. Follow [the EA/Wine procedure](manual-acceptance-wine.md)
and compare direct capture against the read-only Automation exporter before any
production release. Do not bypass incomplete metadata or repository-identity gates.
Recommended next milestone is native version qualification, then targeted cache
memory optimization and verified mappings—not unofficial production access.
