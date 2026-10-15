# Manual acceptance: macOS + Sparx EA through Wine

**Status: NOT RUN. Production release blocker.** Automated Python/Node API fixtures do not substitute for this checklist. Record EA version, MDG BPMN/ArchiMate versions, Wine version, date, and actual results here or in a private test record. Do not attach the company catalogue/repository to Git.

Use your existing working EA/Wine setup. No COM bridge, Windows VM, Wine reinstall or production connection is needed. Use synthetic data and a disposable **local `.qea`** repository. Keep DiagramGene on `127.0.0.1` with the existing authentication settings.

## Prepare a synthetic repository

1. In EA create/open `DiagramGene-acceptance.qea`. Add sibling packages `Catalogue` and `Imports`.
2. Under Catalogue add `OPCO-A` and `OPCO-B`. In A create UML Actor `Manager`, Activities `Persetujuan anggaran` and `Persetujuan pengadaan`; give Manager a distinctive Note and Alias. Optionally add stable `BusinessID` and `OPCO` tags. Create another `Manager` of the same type in B.
3. In A create the two intended Associations from Manager to those Activities, named `bertanggung jawab`, with source-to-destination direction. Record ElementGUID/ElementID and ConnectorGUID/ConnectorID. Give one connector a distinctive role/cardinality/qualifier and a non-secret test tagged value.
4. Add a native BPMN Business Process diagram in A with Pool `Telkom Infra`, Lane `Finance`, two Activities and a Sequence Flow. Create a second Pool with one Activity and a **Message Flow** between Activities in distinct Pools. Use the BPMN toolbox, not generic elements with typed names. Record owning ParentID chains and actual base Types/qualified StereotypeEx values. Enable the BPMN2.0 and ArchiMate3 technologies.

## Export and read-only validation

5. Select Catalogue, run the supplied `export_ea_catalogue.js` as **JScript**. Confirm the model's package/element/connector counts and modified properties did not change. Save only its JSON output privately. Check that hierarchy, IDs, GUIDs, aliases, native stereotypes, Pool/Lane parents and connector metadata agree with EA; Notes and credentials must be absent.
6. If the exporter flags incomplete metadata or cannot verify ConnectionString identity, stop and record the unsupported API/property/connection form. Do not edit the script to bypass the guard. Validate whether your installed EA exposes the supported interface before adapting it.
7. In DiagramGene choose **Local Testing**, upload that snapshot, verify the exact locator reported by EA (possibly a Wine `Z:/...` path), pin Catalogue root, OPCO-A scope GUID and Imports output GUID. Keep `VALIDATE_ONLY`.
8. Upload `examples/manager_dan_proses.drawio`, choose Generic/UML. Bind both Managers to the A Actor, each process to its corresponding Activity, and each relationship to its approved ConnectorGUID. Confirm semantics. For the connector with non-default role/tag properties, inspect the properties in EA before selecting **Accept existing properties**. Download and run validation JScript.
9. Expect PREFLIGHT followed by `VALIDATE_ONLY: repository unchanged.` No package, diagram, element, connector, tagged value or role property may be created/updated. Compare counts, master Notes, parentage, end properties and GUID/ID values, rather than judging by diagram appearance.

## Execution and idempotency

10. Switch to EXECUTE and explicitly approve the current plan. Run in the same local repository. Verify two output diagrams each contain the same canonical Actor ElementID/GUID; the correct processes and existing ConnectorGUIDs are displayed. No master/connector properties or master counts may change.
11. Run the same fully reused script again. New output diagrams/packages are allowed; master and connector counts must remain constant. Inspect DiagramLinks versus repository Connectors separately.
12. Test a genuinely new local Activity and one named Association: approve NEW per element, CREATE per relationship, and the final plan. Check that precisely the approved local objects/relationship are created. Running that old script again against existing masters must request a snapshot refresh when a possibly equivalent connector appeared; it must not duplicate that connector. Fresh snapshots should resolve it for reuse.

## Negative cases: zero writes are mandatory

For each case record counts and GUIDs before and after. **No output package may appear.**

| Case | Expected result |
| --- | --- |
| Switch EA to a copied `.qea` at a different path, retaining identical GUIDs | Repository identity mismatch |
| Bind a missing or out-of-scope GUID | Preflight failure |
| Use an Actor with a different qualified stereotype | Type/stereotype failure |
| Leave two same-name/type candidates unbound across OPCOs | Ambiguity; select correct scope/GUID |
| Map two distinct source objects on one page to one master without confirmation | Collision failure |
| Select the wrong ConnectorGUID, reverse its endpoints or change type/direction | Relationship failure |
| Change role/cardinality/qualifier/tagged value or connector/role Notes after exporting | Stale relationship failure |
| Move a Lane to a different Pool or an Activity into another Lane after exporting | Parent/context failure; no reparenting |
| Use a dangling source connector | Unresolved endpoint blocks import |
| Disable required BPMN/ArchiMate MDG | Failure before any AddNew |
| Select EXECUTE without row/global approvals | Generation/runtime blocked |

## BPMN and ArchiMate acceptance

13. Prepare a synthetic draw.io collaboration reflecting the native Pool/Lane/Activities. Map each object to the corresponding GUID. Reused BPMN elements must keep the exact ParentID/ElementID/GUID. Runtime must not reparent them or change their Notes/tags. A Lane under the wrong Pool must fail.
14. Confirm a Sequence Flow within one process succeeds. A Sequence Flow across Pools or subprocess scope must fail before writing. A Message Flow between distinct Pools and supported Activities must validate/reuse correctly; never accept it becoming Sequence Flow. Gateway/Lane/Data endpoints for Message Flow must fail. Start-incoming/End-outgoing Sequence Flows must fail. Check None/Message event definitions and catch/throw direction against native MDG properties; unsupported event/gateway variants should block.
15. Test Data Association Activity↔Data Object in the same supported scope. It must remain Data Association, with correct native EA base type and qualified stereotype. If the installed MDG disagrees with the supported mapping, stop release and update the mapping/tests based on actual API results; never add a fallback connector.
16. Try a Pool/Lane with a real process/participant/partner/partition reference. This P0 implementation must block references it cannot verify. It must not write a fabricated reference tag or substitute an Actor GUID for a Pool/Lane GUID.
17. In an ArchiMate test diagram validate the supported Assignment, Serving, Access, Realization, Flow, Triggering and Association pairs listed in `semantic_rules.py`. Check base spelling `Realisation`, qualified stereotypes, role properties, all tags and direction. Reverse/invalid type pairs must block. Confirm Access metadata against the actual MDG before approving new creation.

## Failure reconciliation and production policy

18. On a disposable local copy, induce a write failure after successful preflight (for example deny creation in the test output package through an existing supported repository control). Check the created-object ledger reports attempted/created packages/elements/connectors, and that the script claims no rollback. Reconcile manually. Do not induce failures on production or delete canonical objects as recovery.
19. Selecting **Holding Production** with a local snapshot must block: a local clone is not a server identity. Verify production defaults to VALIDATE_ONLY, disallows new elements by default, and requires scope, pinned output GUID, per-new-relationship approval and final approval. Do not connect to the real production server simply to complete this checklist. Actual server/PCS identity verification needs a separate controlled non-production server acceptance test using the organization's approved connection form; opaque DSN/PCS connections must remain blocked.
20. Smoke-test existing compressed draw.io, embedded SVG/PNG, VSDX Generic/BPMN and TRM CSV/XLSX locally. TRM production remains explicitly blocked pending P1; approved local TRM retains its existing generation behavior.

Acceptance requires canonical object **and** relationship identity, correct semantics, and zero-write negative tests. A rendered diagram alone is insufficient. Record pass/fail for each item; any failed relationship or repository-safety case blocks release.
