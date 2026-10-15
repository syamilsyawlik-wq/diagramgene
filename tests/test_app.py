"""Regresi startup, login, dan navigasi tanpa server atau password nyata."""
import os
import io
from pathlib import Path
import secrets
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from model_types import archimate
from vsdx_fixture import make_vsdx
from test_catalogue import catalog_csv, MANAGER, MANAGER_TWO, CATALOGUE

ROOT = Path(__file__).resolve().parents[1]


class AppTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"APP_PASSWORD": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.password = secrets.token_urlsafe(24)

    def app(self, password=None):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20)
        # Gunakan secret dalam memori; tidak membaca secrets pengguna.
        at.secrets = {} if password is None else {"APP_PASSWORD": password}
        return at.run()

    def assert_no_exception(self, at):
        self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])

    def login(self, at, password):
        at.text_input[0].input(password)
        at.button[0].click().run()
        self.assert_no_exception(at)

    def enter_generic(self, at):
        at.radio[0].set_value("Diagram umum → entitas & relasi").run()
        # Existing standalone-import tests deliberately disable catalogue reuse.
        at.checkbox[0].uncheck().run()
        return at

    def test_missing_password_shows_configuration_message(self):
        at = self.app()
        self.assert_no_exception(at)
        self.assertIn("APP_PASSWORD belum diatur", at.error[0].value)
        self.assertEqual(len(at.radio), 0)

    def test_missing_secrets_file_does_not_crash(self):
        with patch("streamlit.runtime.secrets.Secrets._parse") as read_secrets:
            from streamlit.errors import StreamlitSecretNotFoundError
            read_secrets.side_effect = StreamlitSecretNotFoundError("Missing test secrets")
            at = self.app()
        self.assert_no_exception(at)
        self.assertIn("APP_PASSWORD belum diatur", at.error[0].value)

    def test_environment_password_takes_precedence(self):
        with patch.dict(os.environ, {"APP_PASSWORD": self.password}):
            at = self.app(password=secrets.token_urlsafe(24))
            self.login(at, self.password)
        self.assertTrue(at.session_state["authed"])

    def test_wrong_password_cannot_access_modes(self):
        at = self.app(self.password)
        self.login(at, "wrong-password")
        self.assertIn("Password salah", at.error[0].value)
        self.assertEqual(len(at.radio), 0)
        self.assertNotIn("authed", at.session_state)

    def test_login_modes_and_logout(self):
        at = self.app(self.password)
        self.login(at, self.password)
        for label in ["Alur proses → BPMN", "Diagram umum → entitas & relasi",
                      "Portofolio aplikasi (CSV) → TRM"]:
            with self.subTest(mode=label):
                if label == "Diagram umum → entitas & relasi":
                    self.enter_generic(at)
                else:
                    at.radio[0].set_value(label).run()
                self.assert_no_exception(at)
                self.assertEqual(len(at.get("file_uploader")), 1)
        at.session_state["result"] = {"test": "discard on logout"}
        at.sidebar.button[0].click().run()
        self.assert_no_exception(at)
        self.assertNotIn("result", at.session_state)
        self.assertNotIn("authed", at.session_state)
        self.assertEqual(len(at.radio), 0)

    def test_five_wrong_attempts_lock_session(self):
        at = self.app(self.password)
        for _ in range(5):
            self.login(at, "wrong-password")
        at.run()
        self.assert_no_exception(at)
        self.assertIn("Terlalu banyak percobaan", at.error[0].value)
        self.assertEqual(len(at.text_input), 0)

    def test_generic_upload_mapping_and_regeneration(self):
        at = self.app(self.password)
        self.login(at, self.password)
        upload = io.BytesIO((ROOT / "examples/arsitektur_entitas.drawio").read_bytes())
        upload.name = "arsitektur.drawio"

        def choose_server_type(rows, **kwargs):
            if rows and "Tipe elemen" not in rows[0]:
                return rows
            return [{**row, "Tipe elemen": "Node" if row["ID"] == "server" else row["Tipe elemen"]}
                    for row in rows]

        with patch("streamlit.file_uploader", return_value=upload), \
             patch("streamlit.data_editor", side_effect=choose_server_type):
            self.enter_generic(at)
            self.assert_no_exception(at)
            next(b for b in at.button if b.label == "Buat script").click().run()
            self.assert_no_exception(at)
            first = at.session_state["result"]
            items = {i["key"]: i for i in first["pages"][0]["items"]}
            self.assertEqual(items["crm"]["ea_type"], "Class")
            self.assertEqual(items["server"]["ea_type"], "Node")
            self.assertEqual(len(first["pages"][0]["links"]), 5)
            self.assertEqual(len(at.success), 1)

            at.selectbox[0].set_value("Component").run()
            self.assert_no_exception(at)
            self.assertEqual(len(at.success), 0, "Hasil lama harus disembunyikan setelah tipe diubah")
            next(b for b in at.button if b.label == "Buat script").click().run()
            self.assert_no_exception(at)
            second = at.session_state["result"]
            self.assertNotEqual(first["key"], second["key"])
            items = {i["key"]: i for i in second["pages"][0]["items"]}
            self.assertEqual(items["crm"]["ea_type"], "Component")
            self.assertEqual(items["server"]["ea_type"], "Node")
            self.assertEqual(first["pages"][0]["links"], second["pages"][0]["links"])

    def test_generic_mapping_editor_accepts_real_rows(self):
        at = self.app(self.password)
        self.login(at, self.password)
        upload = io.BytesIO((ROOT / "examples/arsitektur_entitas.drawio").read_bytes())
        upload.name = "arsitektur.drawio"
        with patch("streamlit.file_uploader", return_value=upload):
            self.enter_generic(at)
            self.assert_no_exception(at)
            self.assertEqual(len(at.get("data_editor")) + len(at.dataframe), 2)
            next(b for b in at.button if b.label == "Buat script").click().run()
            self.assert_no_exception(at)
            self.assertEqual(len(at.session_state["result"]["pages"][0]["links"]), 5)

    def test_archimate_profile_and_relationship_mapping(self):
        at = self.app(self.password)
        self.login(at, self.password)
        upload = io.BytesIO((ROOT / "examples/arsitektur_entitas.drawio").read_bytes())
        upload.name = "arsitektur.drawio"

        def choose_types(rows, **kwargs):
            for row in rows:
                row = row.copy()
                if "Tipe elemen" in row and row["ID"] == "ai":
                    row["Tipe elemen"] = "ArchiMate: Application Component"
                if "Tipe relasi" in row and row["ID"] == "service_data":
                    row["Tipe relasi"] = "ArchiMate: Access"
                yield row

        with patch("streamlit.file_uploader", return_value=upload), \
             patch("streamlit.data_editor", side_effect=lambda rows, **kw: list(choose_types(rows))):
            self.enter_generic(at)
            next(b for b in at.button if b.label == "Buat script").click().run()
            self.assert_no_exception(at)
            at.radio[1].set_value("ArchiMate 3").run()
            self.assert_no_exception(at)
            self.assertEqual(len(at.success), 0)
            next(b for b in at.button if b.label == "Buat script").click().run()
            self.assert_no_exception(at)
            page = at.session_state["result"]["pages"][0]
            items = {i["key"]: i for i in page["items"]}
            self.assertEqual(items["crm"]["ea_type"], archimate("ApplicationComponent"))
            self.assertEqual(items["ai"]["ea_type"], archimate("ApplicationComponent"))
            self.assertEqual(next(c for c in page["links"] if c["key"] == "service_data")["stereotype"],
                             archimate("Access"))

    def test_visio_upload_in_generic_mode(self):
        at = self.app(self.password)
        self.login(at, self.password)
        upload = io.BytesIO(make_vsdx())
        upload.name = "applications.vsdx"
        with patch("streamlit.file_uploader", return_value=upload):
            self.enter_generic(at)
            self.assert_no_exception(at)
            self.assertEqual(at.multiselect[0].value, ["Applications", "Second"])
            at.multiselect[0].set_value(["Applications"]).run()
            next(b for b in at.button if b.label == "Buat script").click().run()
            self.assert_no_exception(at)
            result = at.session_state["result"]
            self.assertEqual(len(result["pages"]), 1)
            self.assertEqual(len(result["pages"][0]["links"]), 1)

    def test_catalogue_default_requires_valid_package_before_generation(self):
        at = self.app(self.password)
        self.login(at, self.password)
        diagram = io.BytesIO((ROOT / "examples/manager_dan_proses.drawio").read_bytes())
        diagram.name = "manager.drawio"
        with patch("streamlit.file_uploader", side_effect=lambda *a, **kw: None if kw.get("key") == "catalogue_upload" else diagram):
            at.radio[0].set_value("Diagram umum → entitas & relasi").run()
            self.assert_no_exception(at)
            self.assertTrue(at.checkbox[0].value)
            self.assertTrue(next(b for b in at.button if b.label == "Buat script").disabled)
            next(t for t in at.text_input if t.label == "GUID root package katalog").input(CATALOGUE).run()
            self.assert_no_exception(at)
            self.assertFalse(next(b for b in at.button if b.label == "Buat script").disabled)
            next(b for b in at.button if b.label == "Buat script").click().run()
            self.assert_no_exception(at)
            self.assertIn('"package_guid": "' + CATALOGUE, at.session_state["result"]["js"])

    def test_catalogue_metadata_turns_plain_manager_note_into_reference_to_actor(self):
        at = self.app(self.password)
        self.login(at, self.password)
        source = (ROOT / "examples/manager_dan_proses.drawio").read_bytes().replace(b"shape=umlActor", b"shape=note")
        diagram = io.BytesIO(source); diagram.name = "manager.drawio"
        metadata = io.BytesIO(catalog_csv()); metadata.name = "catalogue.csv"
        with patch("streamlit.file_uploader", side_effect=lambda *a, **kw: metadata if kw.get("key") == "catalogue_upload" else diagram):
            at.radio[0].set_value("Diagram umum → entitas & relasi").run()
            self.assert_no_exception(at)
            next(b for b in at.button if b.label == "Buat script").click().run()
            self.assert_no_exception(at)
            result = at.session_state["result"]
            for page in result["pages"]:
                manager = next(i for i in page["items"] if i["key"] == "manager")
                self.assertEqual(manager["ea_type"], "Actor")
                self.assertEqual(manager["catalogue_guid"], MANAGER)
                self.assertEqual(page["links"][0]["ea_type"], "Association")

    def test_ambiguous_catalogue_name_blocks_generation_in_ui(self):
        at = self.app(self.password)
        self.login(at, self.password)
        source = (ROOT / "examples/manager_dan_proses.drawio").read_bytes().replace(b"shape=umlActor", b"shape=note")
        diagram = io.BytesIO(source); diagram.name = "manager.drawio"
        metadata = io.BytesIO(catalog_csv([(MANAGER, "Manager", "Actor", "", "Actors"),
                                         (MANAGER_TWO, "Manager", "Class", "", "Data")]))
        metadata.name = "catalogue.csv"
        with patch("streamlit.file_uploader", side_effect=lambda *a, **kw: metadata if kw.get("key") == "catalogue_upload" else diagram):
            at.radio[0].set_value("Diagram umum → entitas & relasi").run()
            self.assert_no_exception(at)
            self.assertTrue(next(b for b in at.button if b.label == "Buat script").disabled)
            self.assertTrue(any("ambigu" in error.value for error in at.error))


if __name__ == "__main__":
    unittest.main()
