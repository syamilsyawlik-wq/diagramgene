"""Synthetic SQLite and strict EA API stub tests. Real EA acceptance is separate."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from catalogue_snapshot import read_snapshot
from import_plan import build_plan, generate_jscript, propose_decisions, read_source
from qea_reader import QEAError, QEAReader, local_access_policy, probe
from repository_cache import CatalogueCache
from repository_providers import LocalQEARepositoryProvider, JSONSnapshotRepositoryProvider
from repository_profiles import normalise_profile
from qea_fixture import make_qea, synthetic_guid, CAT, ACTOR, PROCESS, CONNECTOR, OUT
from test_repository_import import SOURCE, decisions, fixture_base, manager_document, run_js, bpmn_document


class QEAReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=make_qea(Path(self.temp.name)/'synthetic.qea')
        self.cache=CatalogueCache(Path(self.temp.name)/'derived')
        self.provider=LocalQEARepositoryProvider(self.path,cache=self.cache)

    def write(self,sql,args=()):
        # Test fixture mutation only; production code has no writable SQL connection.
        with sqlite3.connect(self.path) as db: db.execute(sql,args)

    def snapshot_profile(self):
        snapshot=self.provider.catalogue(2)
        profile=normalise_profile({'expected_identity':snapshot['repository_identity'],
            'catalogue_root_guid':CAT,'scope_package_guid':CAT,'output_package_guid':OUT,'qea_identity_reviewed':True})
        return snapshot,profile

    def test_read_enumerate_scope_and_normalized_contract(self):
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertEqual(self.provider.overview()['counts']['t_object'],2)
        self.assertEqual(self.provider.packages(search='Holding')[0]['ea_guid'],CAT)
        self.assertEqual(self.provider.page('elements',2,ea_type='Actor')[0]['guid'],ACTOR)
        self.assertEqual(self.provider.page('relationships',2)[0]['guid'],CONNECTOR)
        self.assertEqual(self.provider.page('diagrams',2)[0]['name'],'Catalogue diagram')
        self.assertEqual(self.provider.page('objects',2)[0]['rectright'],100)
        self.assertEqual(len(self.provider.page('types',2)),2)
        snapshot,_=self.snapshot_profile()
        self.assertTrue(snapshot['repository_source']['trusted_capture'])
        self.assertEqual(snapshot['elements'][0]['guid'],ACTOR)
        self.assertTrue(snapshot['connectors'][0]['metadata_complete'])
        uploaded=JSONSnapshotRepositoryProvider(json.dumps(snapshot)).catalogue()
        self.assertFalse(uploaded['repository_source']['trusted_capture'])
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_sqlite_denies_all_writes_attach_and_extension(self):
        before=self.path.read_bytes()
        reader=QEAReader(self.path)
        with reader.read():
            for statement in ["INSERT INTO t_package VALUES(99,'bad',0,'bad')",'UPDATE t_object SET Name=Name',
                    'DELETE FROM t_object','ALTER TABLE t_object ADD COLUMN bad TEXT',
                    "ATTACH DATABASE ':memory:' AS other","SELECT load_extension('bad')",
                    'PRAGMA query_only=OFF']:
                with self.subTest(statement=statement), self.assertRaises(sqlite3.Error):
                    reader.connection.execute(statement)
        self.assertIsNone(reader.connection)
        self.assertEqual(before,self.path.read_bytes())

    def test_invalid_missing_directory_corrupt_and_qeax(self):
        for target,content in [('not.qea',b'not sqlite'),('unsupported.qeax',b'not sqlite')]:
            p=self.path.parent/target;p.write_bytes(content)
            with self.assertRaises(QEAError): LocalQEARepositoryProvider(p).overview()
        with self.assertRaises(QEAError): probe(self.path.parent/'missing.qea')
        with self.assertRaises(QEAError): probe(self.path.parent)
        self.path.write_bytes(b'SQLite format 3\0'+bytes(500))
        with self.assertRaises(QEAError): self.provider.overview()

    def test_unsupported_schema_and_close_after_error(self):
        self.write('DROP TABLE t_objectproperties')
        reader=QEAReader(self.path)
        with self.assertRaisesRegex(QEAError,'t_objectproperties'):
            with reader.read(): pass
        self.assertIsNone(reader.connection)

    def test_schema_introspection_optional_connector_fields_are_not_invented(self):
        self.write('ALTER TABLE t_connector DROP COLUMN SourceAlias')
        snapshot=self.provider.catalogue(2)
        self.assertFalse(snapshot['connectors'][0]['metadata_complete'])
        self.assertIn('Alias/style',str(snapshot['connectors'][0]['metadata_reasons']))

    def test_reject_journal_wal_and_wal_mode_without_sidecar(self):
        for suffix in ('-wal','-shm','-journal'):
            sidecar=Path(str(self.path)+suffix);sidecar.touch()
            with self.assertRaisesRegex(QEAError,'WAL/journal'): probe(self.path)
            sidecar.unlink()
        with sqlite3.connect(self.path) as db: db.execute('PRAGMA journal_mode=WAL')
        with self.assertRaises(QEAError): self.provider.overview()

    def test_locked_repository_error_is_actionable(self):
        db=sqlite3.connect(self.path);self.addCleanup(db.close)
        db.execute('BEGIN EXCLUSIVE')
        with self.assertRaises(QEAError): self.provider.overview()
        db.rollback()

    def test_backend_policy_and_symlink_escape(self):
        with self.assertRaises(QEAError): local_access_policy('0.0.0.0',{})
        with self.assertRaises(QEAError): local_access_policy('127.0.0.1',{'DIAGRAMGENE_DISABLE_LOCAL_QEA':'true'})
        root=self.path.parent/'allowed';root.mkdir();link=root/'link.qea';link.symlink_to(self.path)
        with self.assertRaisesRegex(QEAError,'di luar'): probe(link,root)
        self.assertEqual(local_access_policy('0.0.0.0',{'DIAGRAMGENE_QEA_ROOT':str(root)}),root)

    def test_query_filters_are_parameters_and_extraction_bounded(self):
        self.assertEqual(self.provider.packages(search="' OR 1=1 --"),[])
        self.assertEqual(self.provider.page('elements',2,guid_filter="' OR 1=1 --"),[])
        with self.assertRaises(QEAError): self.provider.page('elements',2,limit=201)
        with self.assertRaisesRegex(QEAError,'batas metadata'): self.provider.catalogue(2,element_limit=1)
        with self.assertRaises(QEAError):
            with QEAReader(self.path,metadata_bytes=10).read() as reader: reader.extract(2)

    def test_cycles_and_missing_parent_or_endpoint_block_catalogue(self):
        self.write('UPDATE t_object SET ParentID=5 WHERE Object_ID=3')
        self.write('UPDATE t_object SET ParentID=3 WHERE Object_ID=5')
        with self.assertRaisesRegex(QEAError,'siklus'): self.provider.catalogue(2)
        self.write('UPDATE t_object SET ParentID=0')
        self.write('UPDATE t_connector SET End_Object_ID=999')
        with self.assertRaisesRegex(QEAError,'endpoint'): self.provider.catalogue(2)

    def test_qualified_stereotype_memo_hash_unknown_xref_and_no_confidential_text(self):
        self.write("UPDATE t_object SET Stereotype='ArchiMate_BusinessActor' WHERE Object_ID=3")
        self.write('INSERT INTO t_xref VALUES(?,?,?)',(ACTOR,'Stereotypes','@STEREO;Name=ArchiMate_BusinessActor;FQName=ArchiMate3::ArchiMate_BusinessActor;@ENDSTEREO;'))
        self.write('INSERT INTO t_objectproperties VALUES(?,?,?,?)',(3,'privateMemo','<memo>','synthetic-private-body'))
        snapshot=self.provider.catalogue(2)
        self.assertEqual(snapshot['elements'][0]['ea_type'],'ArchiMate3::ArchiMate_BusinessActor')
        self.assertNotIn('synthetic-private-body',json.dumps(snapshot))
        self.write('INSERT INTO t_xref VALUES(?,?,?)',(ACTOR,'CustomSemantics','synthetic-private-description'))
        self.write("UPDATE t_connector SET Notes='synthetic-private-connector-notes'")
        snapshot=self.provider.catalogue(2,force=True)
        self.assertEqual(snapshot['elements'][0]['metadata_status'],'NEEDS_REVIEW')
        self.assertNotIn('synthetic-private',json.dumps(snapshot))

    def test_unqualified_or_unknown_mdg_cannot_reuse(self):
        for stereo in ('BusinessActor','Custom::BusinessActor'):
            self.write('UPDATE t_object SET Stereotype=? WHERE Object_ID=3',(stereo,))
            snapshot=self.provider.catalogue(2,force=True)
            self.assertEqual(snapshot['elements'][0]['metadata_status'],'NEEDS_REVIEW')

    def test_cache_hit_scope_refresh_tamper_and_changed_file(self):
        first=self.provider.catalogue(2)
        with patch.object(QEAReader,'read',side_effect=AssertionError('cache must avoid DB open')):
            self.assertEqual(first,self.provider.catalogue(2));self.assertTrue(self.provider.last_cache_hit)
        self.assertEqual(self.provider.catalogue(1)['elements'],[])
        self.assertFalse(self.provider.last_cache_hit)
        self.provider.catalogue(2,force=True);self.assertFalse(self.provider.last_cache_hit)
        target=next(p for p in self.cache.path.glob('*.json') if json.loads(p.read_text())['scope']==2)
        envelope=json.loads(target.read_text());envelope['catalogue']['elements'][0]['name']='tampered'
        target.write_text(json.dumps(envelope))
        self.assertEqual(self.provider.catalogue(2)['elements'][0]['name'],'Manager')
        self.assertFalse(self.provider.last_cache_hit)
        old=probe(self.path)['fingerprint']
        self.write("UPDATE t_object SET Alias='Changed' WHERE Object_ID=3")
        self.assertNotEqual(old,probe(self.path)['fingerprint'])
        self.assertEqual(self.provider.catalogue(2)['elements'][0]['alias'],'Changed')
        with self.assertRaises(QEAError): LocalQEARepositoryProvider(self.path,expected_fingerprint=old).catalogue(2)

    def test_source_drift_blocks_generation_and_uploaded_provenance_cannot_read_backend(self):
        snapshot,profile=self.snapshot_profile();document=manager_document();elements,relations=decisions(document)
        self.write("UPDATE t_object SET Name='Changed' WHERE Object_ID=3")
        plan=build_plan(document,profile,snapshot,elements,relations)
        self.assertFalse(plan['can_execute']);self.assertIn('berubah',str(plan['errors']))
        uploaded=read_snapshot(json.dumps(snapshot))
        with patch('qea_reader.probe',side_effect=AssertionError('Uploaded JSON must not access filesystem')):
            build_plan(document,profile,uploaded,elements,relations)

    def test_read_transaction_detects_change_and_fingerprint_is_not_mtime_only(self):
        stamp=self.path.stat().st_mtime_ns;old=probe(self.path)['fingerprint']
        self.write("UPDATE t_object SET Alias='same mtime' WHERE Object_ID=3")
        os.utime(self.path,ns=(self.path.stat().st_atime_ns,stamp))
        self.assertNotEqual(old,probe(self.path)['fingerprint'])
        with self.assertRaisesRegex(QEAError,'selama pembacaan'):
            with QEAReader(self.path).read() as reader:
                reader.overview()
                os.utime(self.path,ns=(self.path.stat().st_atime_ns,stamp+100000))

    def test_query_deadline_closes_connection(self):
        reader=QEAReader(self.path,timeout=0)
        with self.assertRaises(QEAError):
            with reader.read():
                reader.rows('WITH RECURSIVE nums(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM nums WHERE n<100000) SELECT n FROM nums',limit=100000)
        self.assertIsNone(reader.connection)

    def test_unknown_memo_identifier_and_connector_style_require_review(self):
        self.write('INSERT INTO t_objectproperties VALUES(?,?,?,?)',(3,'DG_BusinessID','<memo>','private-business-id'))
        self.write('ALTER TABLE t_connector ADD COLUMN SourceStyle TEXT')
        self.write("UPDATE t_connector SET SourceStyle='unsupported-meaning=1;'")
        snapshot=self.provider.catalogue(2)
        self.assertEqual(snapshot['elements'][0]['business_id'],'')
        self.assertEqual(snapshot['elements'][0]['metadata_status'],'NEEDS_REVIEW')
        self.assertFalse(snapshot['connectors'][0]['metadata_complete'])

    def test_unknown_relationship_metadata_cannot_disappear_into_create_proposal(self):
        self.write('ALTER TABLE t_connector DROP COLUMN SourceAlias')
        snapshot,profile=self.snapshot_profile();document=manager_document();elements,relations=decisions(document)
        for page in document['pages']:
            for r in page['relationships']: r['name']='different proposed meaning'
        for r in relations.values(): r.update(existing_connector_guid='',approved_create=True)
        plan=build_plan(document,profile,snapshot,elements,relations)
        self.assertTrue(all(r['action']=='REVIEW' for r in plan['relationships']))
        self.assertFalse(plan['can_execute'])

    def test_actor_proposals_new_actor_ambiguity_and_name_only_review(self):
        snapshot,profile=self.snapshot_profile();document=manager_document()
        proposed=propose_decisions(document,profile,snapshot)
        actors=[n for p in document['pages'] for n in p['nodes'] if n['kind']=='actor']
        self.assertTrue(all(proposed[n['id']]['master_guid']==ACTOR for n in actors))
        for n in actors: n['name']='New Manager'
        proposed=propose_decisions(document,profile,snapshot)
        self.assertTrue(all(proposed[n['id']]['action']=='NEW' and not proposed[n['id']]['approved_new'] for n in actors))
        plan=build_plan(document,profile,snapshot,proposed)
        self.assertFalse(plan['can_execute'])
        self.assertTrue(all(n['ea_type']=='Actor' for n in plan['nodes'] if n['kind']=='actor'))
        for n in actors: n['name']='Manager';n['inferred']=True
        self.assertTrue(all(propose_decisions(document,profile,snapshot)[n['id']]['action']=='REVIEW' for n in actors))
        self.write('INSERT INTO t_package VALUES(10,?,?,?)',('OPCO B',2,synthetic_guid(1000)))
        self.write('INSERT INTO t_object VALUES(?,?,?,?,?,?,?,?)',(10,'Manager','Actor',10,0,synthetic_guid(2000),'',''))
        snapshot=self.provider.catalogue(2)
        for n in actors: n['inferred']=False
        self.assertTrue(all(propose_decisions(document,profile,snapshot)[n['id']]['action']=='REVIEW' for n in actors))
        self.assertFalse(build_plan(document,profile,snapshot,propose_decisions(document,profile,snapshot))['can_execute'])

    def test_identity_review_required_and_local_capture_cannot_authorize_production(self):
        snapshot,profile=self.snapshot_profile();profile['qea_identity_reviewed']=False
        self.assertFalse(build_plan(manager_document(),profile,snapshot)['can_execute'])
        profile.update(environment='production',expected_identity={'kind':'server','server':'synthetic','database':'ea','provider':'MSDASQL'})
        self.assertIn('production',str(build_plan(manager_document(),profile,snapshot)['errors']))

    @unittest.skipUnless(shutil.which('node'),'Node.js required')
    def test_qea_actor_connector_reuse_repeat_and_wrong_repository_zero_writes(self):
        snapshot,profile=self.snapshot_profile();document=manager_document();elements,relations=decisions(document)
        fixture={**fixture_base(),'connectionString':snapshot['repository_identity']['locator']}
        plan=build_plan(document,profile,snapshot,elements,relations)
        self.assertTrue(plan['can_execute'],plan['errors'])
        output=run_js(generate_jscript(plan),{**fixture,'rejectWrites':True})
        self.assertIsNone(output['error'],output['logs']);self.assertEqual(output['mutationAttempts'],0)
        plan=build_plan(document,profile,snapshot,elements,relations,mode='EXECUTE',execute_approved=True)
        output=run_js(generate_jscript(plan),{**fixture,'runs':2})
        self.assertIsNone(output['error'],output['logs'])
        self.assertEqual(len(output['elements']),2);self.assertEqual(len(output['connectors']),1)
        self.assertEqual(output['connectors'][0]['ConnectorGUID'],CONNECTOR)
        self.assertEqual(next(e['ElementID'] for e in output['elements'] if e['ElementGUID']==ACTOR),3)
        output=run_js(generate_jscript(plan),{**fixture,'connectionString':'Z:/wrong.qea','rejectWrites':True})
        self.assertIsNotNone(output['error']);self.assertEqual(output['mutationAttempts'],0)

    def test_bpmn_qea_qualified_parent_tags_and_wrong_parent(self):
        from semantic_rules import BPMN_TYPES
        document=bpmn_document();records=document['pages'][0]['nodes']
        self.write('DELETE FROM t_connector');self.write('DELETE FROM t_object')
        ids={'p':10,'lane':11,'task':12,'task2':13}
        for n in records:
            q=synthetic_guid(ids[n['id']]);stereo=n['ea_type'].split('::')[1]
            self.write('INSERT INTO t_object VALUES(?,?,?,?,?,?,?,?)',(ids[n['id']],n['name'],
                'ActivityPartition' if n['kind'] in ('pool','lane') else 'Activity',2,ids.get(n['parent'],0),q,stereo,''))
            self.write('INSERT INTO t_xref VALUES(?,?,?)',(q,'Stereotypes','@STEREO;FQName='+n['ea_type']+';@ENDSTEREO;'))
            if n['kind']=='task': self.write('INSERT INTO t_objectproperties VALUES(?,?,?,?)',(ids[n['id']],'activityType','Task',''))
            n['inferred']=False
        snapshot,profile=self.snapshot_profile();proposed=propose_decisions(document,profile,snapshot)
        plan=build_plan(document,profile,snapshot,proposed)
        self.assertTrue(all(n['status']=='REUSE' for n in plan['nodes']),[(n['name'],n['reason']) for n in plan['nodes']])
        self.assertEqual({n['ea_type'] for n in plan['nodes']},{BPMN_TYPES[k] for k in ('pool','lane','task')})
        self.write('UPDATE t_object SET ParentID=0 WHERE Object_ID=11')
        snapshot=self.provider.catalogue(2)
        plan=build_plan(document,profile,snapshot,proposed)
        self.assertTrue(any(n['status']=='BLOCK' and n['kind']=='lane' for n in plan['nodes']))


if __name__=='__main__': unittest.main()
