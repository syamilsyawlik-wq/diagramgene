"""AppTest exercises the default local QEA workflow, not a snapshot substitute."""
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from qea_fixture import make_qea, CAT, OUT, ACTOR
from repository_cache import CatalogueCache

ROOT=Path(__file__).resolve().parents[1]


class LocalQEAAppTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=make_qea(Path(self.temp.name)/'synthetic.qea')
        self.cache_patch=patch('repository_providers.CatalogueCache',return_value=CatalogueCache(Path(self.temp.name)/'cache'))
        self.cache_patch.start();self.addCleanup(self.cache_patch.stop)
        self.at=AppTest.from_file(str(ROOT/'app.py'),default_timeout=20).run()

    def assert_ok(self): self.assertEqual(len(self.at.exception),0,[e.message for e in self.at.exception])

    def analyze(self):
        next(t for t in self.at.text_input if t.label=='Path file .qea lokal').input(str(self.path)).run()
        next(b for b in self.at.button if b.label=='Analisis repository').click().run()
        self.assert_ok()

    def choose_scope(self):
        next(s for s in self.at.selectbox if s.label=='Package katalog / scope').set_value(2).run()
        next(s for s in self.at.selectbox if s.label=='Package output diagram').set_value(1).run()
        self.assert_ok()

    def test_local_default_path_analysis_scope_inspection_and_governed_review(self):
        self.assertEqual(self.at.selectbox(key='repository_source').value,'File QEA lokal')
        self.assertFalse(self.at.get('file_uploader'))
        self.analyze();self.choose_scope()
        next(c for c in self.at.checkbox if c.label=='Buka inspector read-only').check().run()
        next(s for s in self.at.selectbox if s.label=='Bagian inspector').set_value('Elemen').run()
        self.assert_ok();self.assertTrue(self.at.dataframe)
        next(c for c in self.at.checkbox if 'pemetaan path Wine' in c.label).check().run()
        source=io.BytesIO((ROOT/'examples/manager_dan_proses.drawio').read_bytes());source.name='manager.drawio'
        with patch('streamlit.file_uploader',return_value=source):
            self.at.radio(key='diagram_mode').set_value('Diagram umum → entitas & relasi').run()
            self.assert_ok()
            self.assertFalse(any(t.label=='GUID root package katalog' for t in self.at.text_input))
            next(b for b in self.at.button if b.label=='Buat script').click().run()
            self.assert_ok();plan=self.at.session_state['result']['import_plan']
            self.assertEqual(plan['mode'],'VALIDATE_ONLY')
            self.assertEqual(plan['profile']['catalogue_root_guid'],CAT)
            self.assertEqual(plan['profile']['output_package_guid'],OUT)
            self.assertTrue(plan['repository_source']['trusted_capture'])
            self.assertTrue(all(n['master_guid']==ACTOR for n in plan['nodes'] if n['kind']=='actor'))
            self.assertFalse(plan['can_execute'])  # Relationship semantics/new process still need review.

    def test_source_change_invalidates_analysis_and_refresh_resets_identity_review(self):
        self.analyze();self.choose_scope()
        next(c for c in self.at.checkbox if 'pemetaan path Wine' in c.label).check().run()
        with sqlite3.connect(self.path) as db: db.execute("UPDATE t_object SET Alias='Changed' WHERE Object_ID=3")
        self.at.run();self.assert_ok()
        self.assertTrue(any('file berubah' in w.value for w in self.at.warning))
        self.assertFalse(any(s.label=='Package katalog / scope' for s in self.at.selectbox))
        next(b for b in self.at.button if b.label=='Segarkan repository').click().run()
        self.assert_ok()
        next(s for s in self.at.selectbox if s.label=='Package katalog / scope').set_value(2).run()
        self.assertFalse(next(c for c in self.at.checkbox if 'pemetaan path Wine' in c.label).value)

    def test_bad_path_and_remote_policy_have_actionable_errors(self):
        next(t for t in self.at.text_input if t.label=='Path file .qea lokal').input('/missing/test.qea').run()
        self.assert_ok();self.assertTrue(any('backend' in e.value for e in self.at.error))
        with patch('repository_inspector.st.get_option',return_value='0.0.0.0'),patch.dict('os.environ',{'DIAGRAMGENE_QEA_ROOT':''}):
            self.at.run()
        self.assert_ok();self.assertTrue(any('non-loopback' in e.value for e in self.at.error))


if __name__=='__main__': unittest.main()
