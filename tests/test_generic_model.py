"""Regresi untuk konversi menjadi entitas model dan relasi yang dapat dipakai di EA."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from generic_mode import convert_generic, list_generic_pages, _legacy_convert_generic

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "examples/arsitektur_entitas.drawio").read_bytes()
MODEL_IDS = {"crm", "service", "customer", "server", "network", "ai"}
EXPECTED_LINKS = {("crm", "service"), ("service", "customer"), ("server", "crm"),
                  ("network", "crm"), ("ai", "crm")}


class GenericModelTests(unittest.TestCase):
    def test_boxes_and_folded_notes_are_real_classes_by_default(self):
        _, pages, _ = convert_generic(SOURCE)
        items = {it["key"]: it for it in pages[0]["items"]}
        for key in MODEL_IDS:
            self.assertEqual(items[key]["ea_type"], "Class")
        self.assertEqual(items["caption"]["ea_type"], "Note")
        self.assertEqual(items["technology_layer"]["ea_type"], "Boundary")
        self.assertEqual({(c["src"], c["tgt"]) for c in pages[0]["links"]}, EXPECTED_LINKS)

    def test_bulk_type_and_per_element_types_preserve_ids_geometry_and_links(self):
        _, before, _ = convert_generic(SOURCE)
        _, after, _ = convert_generic(SOURCE, default_type="Component", element_types={
            "Arsitektur": {"customer": "Class", "server": "Node", "network": "Node", "caption": "Note"}})
        old = {it["key"]: it for it in before[0]["items"]}
        new = {it["key"]: it for it in after[0]["items"]}
        self.assertEqual(new["crm"]["ea_type"], "Component")
        self.assertEqual(new["server"]["ea_type"], "Node")
        self.assertEqual(new["customer"]["ea_type"], "Class")
        for key in old:
            self.assertEqual({k: v for k, v in old[key].items() if k not in ("ea_type", "mapping_basis")},
                             {k: v for k, v in new[key].items() if k not in ("ea_type", "mapping_basis")})
        self.assertEqual(before[0]["links"], after[0]["links"])

    def test_invalid_types_are_rejected_before_generating_script(self):
        with self.assertRaisesRegex(ValueError, "tidak didukung"):
            convert_generic(SOURCE, default_type="InventedType")
        with self.assertRaisesRegex(ValueError, "tidak didukung"):
            convert_generic(SOURCE, element_types={"Arsitektur": {"crm": "InventedType"}})

    def test_generic_page_listing_does_not_describe_text_as_a_process(self):
        source = b'<mxGraphModel><root><mxCell id="1" value="Title" style="text;" vertex="1"><mxGeometry width="100" height="30"/></mxCell></root></mxGraphModel>'
        self.assertEqual(list_generic_pages(source), [("Page-1", "Page-1")])
        self.assertEqual(convert_generic(source)[1][0]["items"][0]["ea_type"], "Note")

    def test_self_relations_and_arrow_directions_are_preserved(self):
        extra = b'''<mxCell id="self" edge="1" source="crm" target="crm" parent="1"/>
        <mxCell id="both" edge="1" source="crm" target="customer" style="startArrow=classic;endArrow=classic;" parent="1"/>
        <mxCell id="back" edge="1" source="crm" target="server" style="startArrow=classic;endArrow=none;" parent="1"/>
        <mxCell id="assoc" edge="1" source="customer" target="server" style="endArrow=none;" parent="1"/>'''
        _, pages, _ = convert_generic(SOURCE.replace(b"</root>", extra + b"</root>"))
        links = pages[0]["links"]
        self.assertTrue(any(c["src"] == c["tgt"] == "crm" for c in links))
        self.assertTrue(any(c["src"] == "crm" and c["tgt"] == "customer" and c["direction"] == "Bi-Directional" for c in links))
        self.assertTrue(any(c["src"] == "server" and c["tgt"] == "crm" for c in links))
        self.assertTrue(any(not c["directed"] and c["direction"] == "Unspecified" for c in links))

    @unittest.skipUnless(shutil.which("node"), "Node.js diperlukan untuk uji eksekusi JScript dengan stub EA")
    def test_generated_jscript_connects_real_elements_in_ea_api(self):
        # Historical core contract; governed public entry points have their own
        # identity/approval/zero-write tests in test_repository_import.py.
        js, _, _ = _legacy_convert_generic(SOURCE, element_types={
            "Arsitektur": {"crm": "Component", "server": "Node"}})
        result = subprocess.run(["node", str(ROOT / "tests/ea_model_stub.js")],
                                input=js, text=True, capture_output=True, check=True)
        output = json.loads(result.stdout)
        elements = {e["Name"]: e for e in output["elements"]}
        self.assertEqual(elements["CRM"]["Type"], "Component")
        self.assertEqual(elements["Server"]["Type"], "Node")
        self.assertEqual(elements["Data pelanggan"]["Type"], "Class")
        self.assertEqual(elements["Business Service B2C"]["Type"], "Class")
        by_id = {e["ElementID"]: e for e in output["elements"]}
        endpoints = {(by_id[c["ClientID"]]["Name"], by_id[c["SupplierID"]]["Name"])
                     for c in output["connectors"]}
        self.assertEqual(endpoints, {("CRM", "Business Service B2C"), ("Business Service B2C", "Data pelanggan"),
                                    ("Server", "CRM"), ("Network", "CRM"), ("AI", "CRM")})
        self.assertEqual(len(output["connectors"]), 5)
        self.assertTrue(all(by_id[c["ClientID"]]["Type"] != "Note" and
                            by_id[c["SupplierID"]]["Type"] != "Note" for c in output["connectors"]))
        self.assertEqual({o["ElementID"] for o in output["diagramObjects"]}, set(by_id))


if __name__ == "__main__":
    unittest.main()
