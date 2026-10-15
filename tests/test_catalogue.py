"""Canonical object reuse: diagram placement must keep the catalogue ElementID."""
import csv
import io
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from ea_catalogue import catalogue_candidates, guid, normalise_catalogue, read_catalogue_csv
# Preserve the historical generator-core regressions. Governed public behavior
# and mandatory preflight are exercised separately in test_repository_import.py.
from generic_mode import _legacy_convert_generic as convert_generic
from model_types import archimate

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "examples/manager_dan_proses.drawio").read_bytes()
CATALOGUE = "{11111111-1111-4111-8111-111111111111}"
MANAGER = "{22222222-2222-4222-8222-222222222222}"
MANAGER_TWO = "{33333333-3333-4333-8333-333333333333}"
PROCESS = "{44444444-4444-4444-8444-444444444444}"


def catalog_csv(entries=None):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["GUID", "Name", "Type", "Stereotype", "PackagePath", "CataloguePackageGUID"])
    for entry in entries or [(MANAGER, "Manager", "Actor", "", "Catalogue / Actors")]:
        writer.writerow([*entry, CATALOGUE])
    return buf.getvalue().encode("utf-8-sig")


class CatalogueMetadataTests(unittest.TestCase):
    def test_csv_retains_guid_type_and_package_path(self):
        data = read_catalogue_csv(catalog_csv())
        self.assertEqual(data["package_guid"], CATALOGUE)
        matches = catalogue_candidates(data["elements"], "  MANAGER\n", "Class")
        self.assertEqual(matches[0]["guid"], MANAGER)
        self.assertEqual(matches[0]["ea_type"], "Actor")
        self.assertEqual(matches[0]["package_path"], "Catalogue / Actors")

    def test_same_name_is_disambiguated_by_type_when_possible(self):
        data = read_catalogue_csv(catalog_csv([(MANAGER, "Manager", "Actor", "", "Actors"),
                                             (MANAGER_TWO, "Manager", "Class", "", "Data")]))
        self.assertEqual([e["guid"] for e in catalogue_candidates(data["elements"], "Manager", "Actor")], [MANAGER])

    def test_archimate_stereotypes_retain_semantic_type(self):
        data = read_catalogue_csv(catalog_csv([(MANAGER, "Manager", "Actor", archimate("BusinessActor"), "Actors")]))
        self.assertEqual(data["elements"][0]["ea_type"], archimate("BusinessActor"))

    def test_invalid_guid_csv_and_policy_are_rejected(self):
        for value in ["", "123", MANAGER[:-1], MANAGER[1:]]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                guid(value)
        self.assertEqual(guid(MANAGER.lower().strip("{}")), MANAGER)
        with self.assertRaisesRegex(ValueError, "Format katalog"):
            read_catalogue_csv(b"Name,Type\nManager,Actor")
        with self.assertRaisesRegex(ValueError, "tidak lengkap"):
            read_catalogue_csv(b"GUID,Name,Type,Stereotype,PackagePath,CataloguePackageGUID\nfoo,Manager")
        with self.assertRaises(ValueError):
            normalise_catalogue({"package_guid": CATALOGUE, "on_missing": "guess"})


@unittest.skipUnless(shutil.which("node"), "Node.js diperlukan untuk uji reuse model melalui stub EA")
class CatalogueRuntimeTests(unittest.TestCase):
    def run_script(self, source=SOURCE, entries=None, options=None, fixture_extra=None, convert_extra=None):
        entries = entries if entries is not None else [{"name": "Manager", "type": "Actor", "guid": MANAGER, "notes": "Canonical actor notes"}]
        options = {"package_guid": CATALOGUE, **(options or {})}
        js, _, _ = convert_generic(source, catalogue=options, **(convert_extra or {}))
        fixture = {"packages": [{"name": "Company catalogue", "guid": CATALOGUE, "elements": entries}],
                   **(fixture_extra or {})}
        result = subprocess.run(["node", str(ROOT / "tests/ea_model_stub.js")],
                                input=json.dumps({"script": js, "fixture": fixture}),
                                text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def assert_no_mutations_after_preflight_failure(self, output):
        self.assertIsNotNone(output["error"])
        self.assertTrue(all(e.get("seeded") for e in output["elements"]))
        self.assertTrue(all(p["seeded"] for p in output["packages"]))
        self.assertEqual(output["connectors"], [])
        self.assertEqual(output["diagramObjects"], [])
        self.assertTrue(all(e["UpdateCalls"] == 0 for e in output["elements"]))

    def test_manager_is_one_canonical_actor_in_two_process_diagrams(self):
        output = self.run_script()
        self.assertIsNone(output["error"])
        actors = [e for e in output["elements"] if e["Type"] == "Actor"]
        self.assertEqual(len(actors), 1)
        manager = actors[0]
        self.assertEqual(manager["ElementGUID"], MANAGER)
        self.assertEqual(manager["Notes"], "Canonical actor notes")
        self.assertEqual(manager["UpdateCalls"], 0)
        self.assertEqual(len([o for o in output["diagramObjects"] if o["ElementID"] == manager["ElementID"]]), 2)
        self.assertEqual(len(output["connectors"]), 2)
        self.assertTrue(all(c["ClientID"] == manager["ElementID"] for c in output["connectors"]))
        self.assertTrue(all(c["Type"] == "Association" for c in output["connectors"]))

    def test_ambiguous_actor_name_stops_before_creating_anything(self):
        output = self.run_script(entries=[{"name": "Manager", "type": "Actor", "guid": MANAGER},
                                          {"name": "Manager", "type": "Actor", "guid": MANAGER_TWO}],
                                 fixture_extra={"expectError": True})
        self.assertIn("ambigu", output["error"])
        self.assert_no_mutations_after_preflight_failure(output)

    def test_explicit_guid_selects_right_actor_and_preserves_catalogue_name(self):
        bindings = {p: {"manager": MANAGER_TWO} for p in ["Persetujuan Anggaran", "Persetujuan Pengadaan"]}
        output = self.run_script(entries=[{"name": "Manager", "type": "Actor", "guid": MANAGER},
                                          {"name": "Manager area bisnis", "type": "Actor", "guid": MANAGER_TWO}],
                                 options={"bindings": bindings})
        self.assertIsNone(output["error"])
        chosen = next(e for e in output["elements"] if e["ElementGUID"] == MANAGER_TWO)
        self.assertEqual(chosen["Name"], "Manager area bisnis")
        self.assertTrue(all(c["ClientID"] == chosen["ElementID"] for c in output["connectors"]))
        self.assertEqual(chosen["UpdateCalls"], 0)

    def test_stale_or_wrong_type_guid_stops_before_creating_anything(self):
        for binding, entries, expected in [
            (MANAGER_TWO, None, "GUID tidak ditemukan"),
            (MANAGER, [{"name": "Manager", "type": "Note", "guid": MANAGER}], "tipe objek katalog berbeda")]:
            with self.subTest(binding=binding, entries=entries):
                output = self.run_script(entries=entries, options={"bindings": {"Persetujuan Anggaran": {"manager": binding}}},
                                         fixture_extra={"expectError": True})
                self.assertIn(expected, output["error"])
                self.assert_no_mutations_after_preflight_failure(output)

    def test_missing_master_is_an_error_instead_of_a_local_duplicate(self):
        output = self.run_script(entries=[], fixture_extra={"expectError": True})
        self.assertIn("objek katalog belum ada", output["error"])
        self.assert_no_mutations_after_preflight_failure(output)

    def test_subpackage_is_searched_but_objects_outside_catalogue_are_excluded(self):
        packages = [{"name": "Catalogue", "guid": CATALOGUE, "children": [
            {"name": "Actors", "guid": PROCESS, "elements": [{"name": "Manager", "type": "Actor", "guid": MANAGER}]}]},
            {"name": "Other catalogue", "guid": MANAGER_TWO,
             "elements": [{"name": "Manager", "type": "Actor", "guid": PROCESS}]}]
        output = self.run_script(fixture_extra={"packages": packages})
        self.assertIsNone(output["error"])
        manager = next(e for e in output["elements"] if e["ElementGUID"] == MANAGER)
        self.assertTrue(all(c["ClientID"] == manager["ElementID"] for c in output["connectors"]))

    def test_guid_binding_cannot_select_an_object_outside_catalogue(self):
        packages = [{"name": "Catalogue", "guid": CATALOGUE},
                    {"name": "Elsewhere", "guid": PROCESS,
                     "elements": [{"name": "Manager", "type": "Actor", "guid": MANAGER}]}]
        output = self.run_script(options={"bindings": {"Persetujuan Anggaran": {"manager": MANAGER}}},
                                 fixture_extra={"packages": packages, "expectError": True})
        self.assertIn("GUID tidak ditemukan", output["error"])
        self.assert_no_mutations_after_preflight_failure(output)

    def test_explicit_creation_policy_creates_one_master_inside_catalogue(self):
        output = self.run_script(entries=[], options={"on_missing": "create"})
        self.assertIsNone(output["error"])
        actors = [e for e in output["elements"] if e["Type"] == "Actor"]
        self.assertEqual(len(actors), 1)
        root = next(p for p in output["packages"] if p["PackageGUID"] == CATALOGUE)
        self.assertEqual(actors[0]["PackageID"], root["PackageID"])
        self.assertTrue(all(c["ClientID"] == actors[0]["ElementID"] for c in output["connectors"]))

    def test_same_name_wrong_type_is_not_matched(self):
        output = self.run_script(entries=[{"name": "Manager", "type": "Class", "guid": MANAGER_TWO},
                                          {"name": "Manager", "type": "Actor", "guid": MANAGER}])
        manager = next(e for e in output["elements"] if e["ElementGUID"] == MANAGER)
        self.assertTrue(all(c["ClientID"] == manager["ElementID"] for c in output["connectors"]))

    def test_existing_relationship_is_reused_across_diagrams_and_repeated_runs(self):
        source = SOURCE.replace(b"Persetujuan pengadaan", b"Persetujuan anggaran")
        output = self.run_script(source=source,
            entries=[{"name": "Manager", "type": "Actor", "guid": MANAGER},
                     {"name": "Persetujuan anggaran", "type": "Activity", "guid": PROCESS}],
            options={"managed_types": ["Actor", "Activity"]},
            fixture_extra={"runs": 2, "connectors": [{"source": MANAGER, "target": PROCESS,
                "name": "bertanggung jawab", "type": "Association", "direction": "Source -> Destination"}]})
        self.assertIsNone(output["error"])
        self.assertEqual(len(output["elements"]), 2)
        self.assertEqual(len(output["connectors"]), 1)
        self.assertTrue(all(e["UpdateCalls"] == 0 for e in output["elements"]))
        self.assertEqual(len(output["diagramLinks"]), 4)
        self.assertEqual({link["ConnectorID"] for link in output["diagramLinks"]}, {output["connectors"][0]["ConnectorID"]})

    def test_archimate_actor_is_reused_with_assignment_to_business_process(self):
        output = self.run_script(entries=[{"name": "Manager", "type": "Actor", "guid": MANAGER,
                                           "stereotype": archimate("BusinessActor")}],
            convert_extra={"profile": "archimate", "element_types": {
                p: {"process": archimate("BusinessProcess")} for p in ["Persetujuan Anggaran", "Persetujuan Pengadaan"]}})
        self.assertIsNone(output["error"])
        self.assertEqual(len([e for e in output["elements"] if e.get("seeded")]), 1)
        self.assertTrue(all(c["StereotypeEx"] == archimate("Assignment") for c in output["connectors"]))

    def test_catalogue_export_is_read_only_and_round_trips_metadata(self):
        script = (ROOT / "export_ea_catalogue.js").read_text()
        fixture = {"selectedPackageGuid": CATALOGUE, "packages": [{"name": "Actors", "guid": CATALOGUE,
                    "elements": [{"name": 'Manager "Area A"', "type": "Actor", "guid": MANAGER}]}]}
        output = json.loads(subprocess.run(["node", str(ROOT / "tests/ea_model_stub.js")],
                            input=json.dumps({"script": script, "fixture": fixture}), text=True,
                            capture_output=True, check=True).stdout)
        self.assertIsNone(output["error"])
        self.assertEqual(output["elements"][0]["UpdateCalls"], 0)
        data = read_catalogue_csv("\n".join(output["logs"]))
        self.assertEqual(data["package_guid"], CATALOGUE)
        self.assertEqual(data["elements"][0]["name"], 'Manager "Area A"')


if __name__ == "__main__":
    unittest.main()
