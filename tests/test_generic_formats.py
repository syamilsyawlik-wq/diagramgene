import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import unittest
import urllib.parse
import zipfile
import zlib

from drawio_to_sparx import convert
from generic_mode import convert_generic, list_generic_pages
from model_types import archimate
from vsdx_fixture import make_vsdx

ROOT = Path(__file__).resolve().parents[1]
DRAWIO = (ROOT / "examples/arsitektur_entitas.drawio").read_bytes()


class GenericFormatTests(unittest.TestCase):
    def test_visio_generic_preserves_shapes_text_geometry_and_glued_relationships(self):
        source = make_vsdx()
        self.assertEqual(list_generic_pages(source), [("Applications", "Applications"), ("Second", "Second")])
        _, pages, notes = convert_generic(source, page_names=["Applications"])
        self.assertEqual(notes, [])
        self.assertEqual(len(pages), 1)
        items = {i["key"]: i for i in pages[0]["items"]}
        self.assertEqual(items["v2"]["text"], "CRM")
        self.assertEqual(items["v2"]["ea_type"], "Class")
        self.assertEqual(items["v5"]["ea_type"], "Note")
        self.assertEqual(items["v1"]["ea_type"], "Boundary")
        self.assertEqual(items["v2"]["r"] - items["v2"]["l"], 144)
        self.assertEqual(items["v3"]["l"] - items["v2"]["l"], 384)
        self.assertEqual([(c["src"], c["tgt"], c["name"]) for c in pages[0]["links"]], [("v2", "v3", "sync")])

    def test_visio_archimate_layer_mapping(self):
        _, pages, _ = convert_generic(make_vsdx(), profile="archimate")
        for page in pages:
            items = {i["key"]: i for i in page["items"]}
            self.assertEqual(items["v2"]["ea_type"], archimate("ApplicationComponent"))
            self.assertIn("lapisan", items["v2"]["mapping_basis"])
            self.assertEqual(page["links"][0]["stereotype"], archimate("Association"))

    def test_visio_without_glue_snaps_to_entities_instead_of_large_container(self):
        original = io.BytesIO(make_vsdx())
        output = io.BytesIO()
        with zipfile.ZipFile(original) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                raw = source.read(item)
                if item.filename.endswith(("page1.xml", "page2.xml")):
                    raw = raw.split(b"<Connects>")[0] + b"</PageContents>"
                target.writestr(item.filename, raw)
        _, pages, _ = convert_generic(output.getvalue())
        self.assertEqual([(c["src"], c["tgt"]) for c in pages[0]["links"]], [("v2", "v3")])

    def test_visio_master_symbol_keeps_one_entity_and_remaps_child_ports(self):
        _, pages, _ = convert_generic(make_vsdx(master_symbol=True), profile="archimate")
        items = {i["key"]: i for i in pages[0]["items"]}
        self.assertNotIn("v20", items)
        self.assertEqual(items["v2"]["text"], "CRM")
        self.assertEqual(items["v2"]["ea_type"], archimate("Node"))
        self.assertEqual([(c["src"], c["tgt"]) for c in pages[0]["links"]], [("v2", "v3")])

    def test_visio_bpmn_reader_still_handles_process_shapes(self):
        _, pages, _ = convert(make_vsdx(), page_names=["Applications"])
        self.assertEqual(len(pages[0]["nodes"]), 2)
        self.assertEqual(len(pages[0]["flows"]), 1)

    def test_png_with_embedded_drawio_works_in_generic_mode(self):
        def chunk(kind, body):
            return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        png = (b"\x89PNG\r\n\x1a\n" +
               chunk(b"zTXt", b"mxfile\x00\x00" + zlib.compress(urllib.parse.quote(DRAWIO.decode()).encode())) +
               chunk(b"IEND", b""))
        _, pages, _ = convert_generic(png)
        self.assertEqual(len(pages[0]["links"]), 5)
        self.assertTrue(all(i["ea_type"] == "Class" for i in pages[0]["items"] if i["key"] in {"crm", "service"}))

    def test_plain_png_and_invalid_visio_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "tidak berisi data draw.io"):
            convert_generic(b"\x89PNG\r\n\x1a\n")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("not-visio.txt", "test")
        with self.assertRaisesRegex(ValueError, "Struktur .vsdx"):
            convert_generic(buf.getvalue())

    def test_archimate_entities_relationships_and_manual_override(self):
        js, pages, _ = convert_generic(DRAWIO, profile="archimate", element_types={
            "Arsitektur": {"ai": archimate("ApplicationComponent")}}, relation_types={
            "Arsitektur": {"crm_service": "ArchiMate: Serving", "service_data": "ArchiMate: Access"}})
        items = {i["key"]: i for i in pages[0]["items"]}
        self.assertEqual(items["crm"]["ea_type"], archimate("ApplicationComponent"))
        self.assertEqual(items["service"]["ea_type"], archimate("BusinessService"))
        self.assertEqual(items["customer"]["ea_type"], archimate("DataObject"))
        self.assertEqual(items["server"]["ea_type"], archimate("Node"))
        self.assertEqual(items["network"]["ea_type"], archimate("CommunicationNetwork"))
        self.assertEqual(items["ai"]["ea_type"], archimate("ApplicationComponent"))
        self.assertEqual(items["ai"]["mapping_basis"], "pilihan pengguna")
        relations = {r["key"]: r for r in pages[0]["links"]}
        self.assertEqual(relations["crm_service"]["stereotype"], archimate("Serving"))
        self.assertEqual(relations["service_data"]["stereotype"], archimate("Access"))

    @unittest.skipUnless(shutil.which("node"), "Node.js diperlukan untuk uji JScript")
    def test_archimate_jscript_creates_typed_model_and_relations(self):
        js, _, _ = convert_generic(DRAWIO, profile="archimate", relation_types={
            "Arsitektur": {"service_data": "ArchiMate: Access"}})
        output = json.loads(subprocess.run(["node", str(ROOT / "tests/ea_model_stub.js")],
                            input=js, text=True, capture_output=True, check=True).stdout)
        elements = {e["Name"]: e for e in output["elements"]}
        self.assertEqual(elements["CRM"]["Type"], archimate("ApplicationComponent"))
        customer_id = elements["Data pelanggan"]["ElementID"]
        link = next(c for c in output["connectors"] if c["SupplierID"] == customer_id)
        self.assertEqual(link["StereotypeEx"], archimate("Access"))
        self.assertEqual(len(output["connectors"]), 5)
