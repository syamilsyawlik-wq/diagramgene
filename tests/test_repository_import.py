"""Governed public entry points and strict Automation API contract fixtures.

These tests do NOT establish compatibility with a real Sparx/MDG installation.
Use docs/manual-acceptance-wine.md before any production release.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from catalogue_snapshot import read_snapshot
from ea_catalogue import guid
from generic_mode import convert_generic
from import_plan import (END_DEFAULTS, build_plan, canonical, fingerprint,
                         generate_jscript, read_source)
from model_types import archimate
from repository_profiles import load_profiles, normalise_profile, save_profiles
from semantic_rules import relation_error

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'examples/manager_dan_proses.drawio').read_bytes()
CAT='{11111111-1111-4111-8111-111111111111}'
ACTOR='{22222222-2222-4222-8222-222222222222}'
PROCESS='{33333333-3333-4333-8333-333333333333}'
OTHER='{44444444-4444-4444-8444-444444444444}'
OUT='{55555555-5555-4555-8555-555555555555}'
CONNECTOR='{66666666-6666-4666-8666-666666666666}'
LANE='{77777777-7777-4777-8777-777777777777}'
POOL='{88888888-8888-4888-8888-888888888888}'
CHILD='{99999999-9999-4999-8999-999999999999}'


def run_js(script, fixture=None):
    result=subprocess.run(['node',str(ROOT/'tests/ea_model_stub.js')],
        input=json.dumps({'script':script,'fixture':{'expectError':True,**(fixture or {})}}),
        text=True,capture_output=True,check=True)
    return json.loads(result.stdout)


def fixture_base():
    return {'packages':[{'name':'Holding catalogue','guid':CAT,'elements':[
        {'name':'Manager','type':'Actor','guid':ACTOR,'notes':'Do not overwrite canonical notes'},
        {'name':'Approval','type':'Activity','guid':PROCESS}]}],
        'connectors':[{'guid':CONNECTOR,'source':ACTOR,'target':PROCESS,'name':'bertanggung jawab',
                       'type':'Association','direction':'Source -> Destination'}]}


def export(fixture):
    output=run_js((ROOT/'export_ea_catalogue.js').read_text(),{**fixture,'selectedPackageGuid':CAT,'rejectWrites':True})
    if output['error']: raise AssertionError(output['error'])
    if output['mutationAttempts']: raise AssertionError('Exporter attempted writes')
    return read_snapshot(output['logs'][-1])


def profile(snapshot, production=False):
    return normalise_profile({'environment':'production' if production else 'local',
        'expected_identity':snapshot['repository_identity'],'catalogue_root_guid':CAT,
        'scope_package_guid':CAT,'output_package_guid':OUT})


def manager_document():
    return read_source(SOURCE.replace(b'Persetujuan pengadaan',b'Persetujuan anggaran'))


def decisions(document, relation_guid=CONNECTOR):
    elements={n['id']:{'action':'REUSE','master_guid':ACTOR if n['kind']=='actor' else PROCESS}
              for p in document['pages'] for n in p['nodes']}
    relations={r['id']:{'semantic_confirmed':True,'existing_connector_guid':relation_guid}
               for p in document['pages'] for r in p['relationships']}
    return elements,relations


@unittest.skipUnless(shutil.which('node'),'Node.js required for strict EA API contract fixtures')
class GovernedImportTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_base();self.snapshot=export(self.fixture)
        self.profile=profile(self.snapshot);self.document=manager_document()
        self.elements,self.relations=decisions(self.document)

    def plan(self, **kwargs):
        return build_plan(self.document,self.profile,self.snapshot,self.elements,self.relations,**kwargs)

    def no_writes(self, output):
        self.assertIsNotNone(output['error'])
        self.assertEqual(output['mutationAttempts'],0,output['logs'])
        self.assertTrue(all(p['seeded'] for p in output['packages']))
        self.assertFalse(output['diagrams'])

    def test_validate_only_uses_zero_mutators(self):
        plan=self.plan()
        self.assertTrue(plan['can_execute'])
        out=run_js(generate_jscript(plan),{**self.fixture,'rejectWrites':True})
        self.assertIsNone(out['error'],out['logs'])
        self.assertEqual(out['mutationAttempts'],0)
        self.assertIn('repository unchanged',out['logs'][-1])

    def test_actor_and_connector_guid_are_reused_across_two_diagrams_and_runs(self):
        plan=self.plan(mode='EXECUTE',execute_approved=True)
        out=run_js(generate_jscript(plan),{**self.fixture,'runs':2})
        self.assertIsNone(out['error'],out['logs'])
        self.assertEqual(len(out['elements']),2)
        self.assertEqual(len(out['connectors']),1)
        self.assertEqual(out['connectors'][0]['ConnectorGUID'],CONNECTOR)
        actor=next(e for e in out['elements'] if e['ElementGUID']==ACTOR)
        self.assertEqual(actor['ElementID'],next(e['id'] for e in self.snapshot['elements'] if e['guid']==ACTOR))
        self.assertEqual(actor['UpdateCalls'],0)
        self.assertEqual(actor['Notes'],'Do not overwrite canonical notes')
        self.assertEqual(len([o for o in out['diagramObjects'] if o['ElementID']==actor['ElementID']]),4)
        self.assertEqual(len(out['diagramLinks']),4)
        self.assertEqual({c['ClientID'] for c in out['connectors']},{actor['ElementID']})

    def test_public_generic_entry_point_uses_governed_runtime(self):
        script,_,_=convert_generic(SOURCE,repository_profile=self.profile,snapshot=self.snapshot,
            element_decisions=self.elements,relationship_decisions=self.relations,
            execution_mode='EXECUTE',execute_approved=True)
        out=run_js(script,self.fixture)
        self.assertIsNone(out['error'],out['logs'])
        self.assertEqual(len(out['connectors']),1)

    def test_repository_clone_with_same_guids_but_different_locator_is_rejected(self):
        out=run_js(generate_jscript(self.plan(mode='EXECUTE',execute_approved=True)),
                   {**self.fixture,'connectionString':'Z:/EA/another-clone.qea'})
        self.assertIn('identity',out['error']);self.no_writes(out)

    def test_opaque_repository_identity_is_rejected_without_disclosing_credentials(self):
        secret='Password=synthetic-secret;DSN=opaque'
        out=run_js(generate_jscript(self.plan()),{**self.fixture,'connectionString':secret})
        self.no_writes(out)
        self.assertNotIn('synthetic-secret',str(out['logs']))

    def test_snapshot_profile_mismatch_blocks_before_output_creation(self):
        self.profile['expected_identity']['locator']='Z:/EA/mismatch.qea'
        plan=self.plan(mode='EXECUTE',execute_approved=True)
        self.assertTrue(plan['errors'])
        self.no_writes(run_js(generate_jscript(plan),self.fixture))

    def test_missing_guid_wrong_stereotype_and_wrong_package_block(self):
        for changed in ('missing','stereotype','scope'):
            with self.subTest(changed=changed):
                fixture=copy.deepcopy(self.fixture)
                if changed=='missing': fixture['packages'][0]['elements'][0]['guid']=OTHER;fixture['connectors']=[]
                if changed=='stereotype': fixture['packages'][0]['elements'][0]['stereotype']=archimate('BusinessActor')
                if changed=='scope':
                    actor=fixture['packages'][0]['elements'].pop(0)
                    fixture['packages'].append({'guid':OTHER,'name':'Other OPCO','elements':[actor]})
                self.no_writes(run_js(generate_jscript(self.plan(mode='EXECUTE',execute_approved=True)),fixture))

    def test_ambiguous_name_and_live_ambiguity_require_explicit_guid(self):
        self.fixture['packages'][0]['elements'].append({'name':'Manager','type':'Actor','guid':OTHER})
        snapshot=export(self.fixture)
        for choice in self.elements.values():
            if choice['master_guid']==ACTOR: choice['master_guid']=''
        plan=build_plan(self.document,self.profile,snapshot,self.elements,self.relations)
        self.assertTrue(any(n['status']=='BLOCK' for n in plan['nodes']))
        self.no_writes(run_js(generate_jscript(plan),self.fixture))
        # The ambiguity may arise after export, too.
        original=copy.deepcopy(self.snapshot)
        plan=build_plan(self.document,self.profile,original,self.elements,self.relations)
        self.no_writes(run_js(generate_jscript(plan),self.fixture))

    def test_endpoint_orientation_and_semantic_type_conflict_are_rejected(self):
        for field,value in [('source',PROCESS),('type','Dependency'),('direction','Unspecified')]:
            with self.subTest(field=field):
                fixture=copy.deepcopy(self.fixture);fixture['connectors'][0][field]=value
                self.no_writes(run_js(generate_jscript(self.plan(mode='EXECUTE',execute_approved=True)),fixture))

    def test_relationship_tag_role_and_qualifier_changes_are_rejected(self):
        for extra in [{'tags':{'meaning':'changed'}},{'source_role':{'Role':'owner'}},{'target_role':{'Qualifier':'OPCO-B'}},
                      {'notes':'Changed relationship meaning'},{'source_role':{'RoleNote':'Changed role meaning'}}]:
            with self.subTest(extra=extra):
                fixture=copy.deepcopy(self.fixture);fixture['connectors'][0].update(extra)
                self.no_writes(run_js(generate_jscript(self.plan(mode='EXECUTE',execute_approved=True)),fixture))

    def test_missing_connector_guid_stops_without_writes(self):
        for choice in self.relations.values(): choice['existing_connector_guid']=OTHER
        self.no_writes(run_js(generate_jscript(self.plan(mode='EXECUTE',execute_approved=True)),self.fixture))

    def test_duplicate_unnamed_relationship_proposals_require_manual_meaning(self):
        self.fixture['connectors']=[];self.snapshot=export(self.fixture)
        for page in self.document['pages']:
            for r in page['relationships']: r['name']=''
        self.relations={key:{'semantic_confirmed':True,'approved_create':True} for key in self.relations}
        plan=self.plan(mode='EXECUTE',execute_approved=True)
        self.assertEqual(plan['relationship_summary']['REVIEW'],2)
        self.no_writes(run_js(generate_jscript(plan),self.fixture))

    def test_distinct_source_objects_cannot_collapse_into_one_master(self):
        page=self.document['pages'][0];duplicate=copy.deepcopy(next(n for n in page['nodes'] if n['kind']=='actor'))
        duplicate.update(id=page['id']+'/other-manager',source_element_id='other-manager')
        page['nodes'].append(duplicate);self.elements[duplicate['id']]={'action':'REUSE','master_guid':ACTOR}
        plan=self.plan();self.assertGreater(plan['summary']['BLOCK'],0)
        self.no_writes(run_js(generate_jscript(plan),self.fixture))

    def test_explicit_new_does_not_merge_same_named_source_objects(self):
        page=self.document['pages'][0]
        page['relationships']=[];self.document['pages']=[page]
        page['nodes'][0]['name']='Uncatalogued object';page['nodes'][1]['name']='Uncatalogued object'
        for n in page['nodes']: n['ea_type']='Class'
        self.elements={n['id']:{'action':'NEW','approved_new':True} for n in page['nodes']}
        out=run_js(generate_jscript(self.plan(mode='EXECUTE',execute_approved=True)),self.fixture)
        self.assertIsNone(out['error'],out['logs'])
        new=[e for e in out['elements'] if not e.get('seeded')]
        self.assertEqual(len(new),2)
        self.assertEqual(len({e['ElementGUID'] for e in new}),2)

    def test_available_master_blocks_accidental_new(self):
        for node in self.document['pages'][0]['nodes']:
            if node['kind']=='actor': self.elements[node['id']]={'action':'NEW','approved_new':True}
        self.assertGreater(self.plan()['summary']['REVIEW'],0)

    def test_explicit_new_annotation_preserves_text_without_touching_master_notes(self):
        self.document['pages']=self.document['pages'][:1];page=self.document['pages'][0];page['relationships']=[]
        node=page['nodes'][0];node.update(name='Local annotation\nsecond line',ea_type='Note')
        page['nodes']=[node];self.elements={node['id']:{'action':'NEW','approved_new':True}}
        out=run_js(generate_jscript(self.plan(mode='EXECUTE',execute_approved=True)),self.fixture)
        self.assertIsNone(out['error'],out['logs'])
        note=next(e for e in out['elements'] if not e.get('seeded'))
        self.assertEqual(note['Notes'],'Local annotation\r\nsecond line')
        self.assertTrue(all(e['UpdateCalls']==0 for e in out['elements'] if e.get('seeded')))

    def test_production_new_relationship_requires_per_row_and_plan_approval(self):
        fixture=copy.deepcopy(self.fixture);fixture['connectors']=[]
        fixture['connectionString']='Provider=MSOLEDBSQL;Data Source=synthetic-server;Initial Catalog=holding;User ID=test;Password=synthetic-secret'
        snapshot=export(fixture);production=profile(snapshot,True)
        rows={key:{'semantic_confirmed':True} for key in self.relations}
        plan=build_plan(self.document,production,snapshot,self.elements,rows,mode='EXECUTE',execute_approved=True)
        self.assertFalse(plan['can_execute']);self.no_writes(run_js(generate_jscript(plan),fixture))
        for r in rows.values(): r['approved_create']=True
        plan=build_plan(self.document,production,snapshot,self.elements,rows,mode='EXECUTE',execute_approved=True)
        self.assertTrue(plan['can_execute'])
        out=run_js(generate_jscript(plan),fixture)
        self.assertIsNone(out['error'],out['logs'])
        # Two pages, one explicitly named model relation, two DiagramLinks.
        self.assertEqual(len(out['connectors']),1)
        self.assertEqual(len(out['diagramLinks']),2)
        repeated=run_js(generate_jscript(plan),{**fixture,'runs':2})
        self.assertIsNotNone(repeated['error'])
        self.assertEqual(len(repeated['connectors']),1)  # Refresh required; never silently duplicate.

    def test_production_source_notation_does_not_approve_existing_relationship(self):
        fixture=copy.deepcopy(self.fixture)
        fixture['connectionString']='Provider=test;Server=synthetic;Database=holding'
        snapshot=export(fixture);production=profile(snapshot,True)
        for p in self.document['pages']:
            for r in p['relationships']: r['semantic_confirmed']=True
        rows={key:{'existing_connector_guid':CONNECTOR} for key in self.relations}
        plan=build_plan(self.document,production,snapshot,self.elements,rows,mode='EXECUTE',execute_approved=True)
        self.assertFalse(plan['can_execute'])
        self.no_writes(run_js(generate_jscript(plan),fixture))

    def test_plan_approval_is_invalidated_after_edit(self):
        plan=self.plan(mode='EXECUTE',execute_approved=True)
        plan['nodes'][0]['name']='edited after approval'
        self.no_writes(run_js(generate_jscript(plan),self.fixture))

    def test_dangling_source_relationship_blocks_all_writes(self):
        self.document['pages'][0]['unresolved_relationships']=[{'id':'dangling'}]
        plan=self.plan(mode='EXECUTE',execute_approved=True)
        self.assertFalse(plan['can_execute'])
        self.no_writes(run_js(generate_jscript(plan),self.fixture))

    def test_reader_reports_dangling_source_edge_instead_of_silently_omitting_it(self):
        document=read_source(SOURCE.replace(b'target="process"',b'target="missing"',1))
        self.assertTrue(document['pages'][0]['unresolved_relationships'])
        plan=build_plan(document,self.profile,self.snapshot,self.elements,self.relations)
        self.assertFalse(plan['can_execute'])

    def test_master_appearing_after_snapshot_blocks_accidental_new(self):
        self.document['pages']=self.document['pages'][:1];page=self.document['pages'][0];page['relationships']=[]
        page['nodes']=[copy.deepcopy(next(n for n in page['nodes'] if n['kind']=='actor'))]
        page['nodes'][0]['name']='New Manager'
        self.elements={page['nodes'][0]['id']:{'action':'NEW','approved_new':True}}
        plan=self.plan(mode='EXECUTE',execute_approved=True)
        self.assertTrue(plan['can_execute'])
        fixture=copy.deepcopy(self.fixture)
        fixture['packages'][0]['elements'].append({'name':'New Manager','type':'Actor','guid':OTHER})
        self.no_writes(run_js(generate_jscript(plan),fixture))

    def test_access_mode_conflict_cannot_be_overridden_by_accept_properties(self):
        fixture=copy.deepcopy(self.fixture)
        fixture['packages'][0]['elements'][0].update(type='Component',stereotype=archimate('ApplicationComponent'))
        fixture['packages'][0]['elements'][1].update(type='Class',stereotype=archimate('DataObject'))
        fixture['connectors'][0].update(type='Dependency',stereotype=archimate('Access'),tags={'accessType':'Write'})
        snapshot=export(fixture)
        for node in self.document['pages'][0]['nodes']+self.document['pages'][1]['nodes']:
            self.elements[node['id']]['ea_type']=archimate('ApplicationComponent' if node['kind']=='actor' else 'DataObject')
        for choice in self.relations.values():
            choice.update(relationship_type='ArchiMate: Access',tags={'accessType':'Read'},accept_existing_properties=True)
        plan=build_plan(self.document,self.profile,snapshot,self.elements,self.relations)
        self.assertTrue(all(r['action']=='BLOCK' for r in plan['relationships']))
        self.no_writes(run_js(generate_jscript(plan),fixture))
        for choice in self.relations.values(): choice['tags']['accessType']='Write'
        plan=build_plan(self.document,self.profile,snapshot,self.elements,self.relations)
        self.assertTrue(plan['can_execute'])
        self.assertIsNone(run_js(generate_jscript(plan),{**fixture,'rejectWrites':True})['error'])

    def test_trm_retains_local_validation_and_blocks_production_writes(self):
        from trm_mode import convert_trm
        source=(ROOT/'examples/portofolio_aplikasi.csv').read_bytes()
        script,_,_,_=convert_trm(source,repository_profile=self.profile)
        out=run_js(script,{**self.fixture,'rejectWrites':True})
        self.assertIsNone(out['error']);self.assertEqual(out['mutationAttempts'],0)
        fixture=copy.deepcopy(self.fixture)
        fixture['connectionString']='Provider=test;Server=synthetic;Database=holding;UID=user;PWD=synthetic-secret'
        production=profile(export(fixture),True)
        script,_,_,_=convert_trm(source,repository_profile=production,execution_mode='EXECUTE',execute_approved=True)
        self.no_writes(run_js(script,fixture))

    def test_matching_business_name_from_another_opco_cannot_be_reused(self):
        for page in self.document['pages']:
            for node in page['nodes']:
                if node['kind']=='actor': node['opco']='OPCO-A'
        for master in self.snapshot['elements']:
            if master['guid']==ACTOR: master['opco']='OPCO-B'
        plan=self.plan(mode='EXECUTE',execute_approved=True)
        self.assertGreater(plan['summary']['BLOCK'],0)
        self.no_writes(run_js(generate_jscript(plan),self.fixture))

    def test_partial_write_failure_reports_ledger_without_rollback(self):
        out=run_js(generate_jscript(self.plan(mode='EXECUTE',execute_approved=True)),
                   {**self.fixture,'failUpdateKind':'diagram'})
        self.assertIsNotNone(out['error'])
        ledger=json.loads(out['logs'][-1]);self.assertEqual(ledger['phase'],'WRITE_FAILURE')
        self.assertFalse(ledger['rollback']);self.assertGreater(len(ledger['created']),0)

    def test_alias_requires_explicit_guid_and_business_id_can_disambiguate(self):
        for el in self.snapshot['elements']:
            if el['guid']==ACTOR: el.update(name='Canonical Manager',alias='Manager',business_id='HOLD-ACTOR-1')
        for choice in self.elements.values():
            if choice['master_guid']==ACTOR: choice['master_guid']=''
        self.assertGreater(self.plan()['summary']['BLOCK'],0)
        for choice in self.elements.values():
            if not choice['master_guid']: choice['business_id']='HOLD-ACTOR-1'
        self.assertEqual(self.plan()['summary']['BLOCK'],0)

    def test_export_whitelists_metadata_and_never_exports_notes_or_connection_string(self):
        fixture=copy.deepcopy(self.fixture)
        fixture['connectionString']='Provider=MSOLEDBSQL;Server=synthetic;Database=test;UID=user;PWD=synthetic-secret'
        fixture['connectors'][0]['notes']='Private relationship meaning'
        fixture['connectors'][0]['source_role']={'RoleNote':'Private role meaning'}
        snapshot=export(fixture)
        serialized=json.dumps(snapshot)
        self.assertNotIn('synthetic-secret',serialized)
        self.assertNotIn('Do not overwrite canonical notes',serialized)
        self.assertNotIn('ConnectionString',serialized)
        self.assertNotIn('Private relationship meaning',serialized)
        self.assertNotIn('Private role meaning',serialized)
        self.assertEqual(snapshot['repository_identity'],{'kind':'server','server':'synthetic','database':'test','provider':'MSOLEDBSQL'})

    def test_python_js_canonical_digest_matches_unicode_and_control_characters(self):
        value={'text':'Manager\nFinance\t\u2028😀','tags':{'z':'','é':'a'},'a':[True,None,12]}
        js=(ROOT/'runtime/metadata.js').read_text()+'\nSession.Output(dgSha256(dgJson('+json.dumps(value)+')));'
        self.assertEqual(run_js(js)['logs'],[fingerprint(value)])
        for value in ('','abc','😀'*60):
            js=(ROOT/'runtime/metadata.js').read_text()+'\nSession.Output(dgSha256('+json.dumps(value)+'));'
            self.assertEqual(run_js(js)['logs'],[hashlib.sha256(value.encode()).hexdigest()])


def bpmn_document():
    def node(key,kind,parent=None,pool='p',scope='p'):
        from semantic_rules import BPMN_TYPES
        return {'id':key,'source_document_id':'synthetic','source_page_id':'page','source_element_id':key,
            'name':key,'ea_type':BPMN_TYPES[kind],'kind':kind,'parent':parent,'pool':pool,'process_scope':scope,
            'geometry':{'l':0,'t':0,'r':200,'b':100},'original_shape':''}
    nodes=[node('p','pool'),node('lane','lane','p'),node('task','task','lane'),node('task2','task','lane')]
    rel={'id':'flow','source':'task','target':'task2','relationship_type':'BPMN: Sequence Flow','name':'approved order',
         'direction':'Source -> Destination','semantic_confirmed':True,'tags':{},'source_role':dict(END_DEFAULTS),'target_role':dict(END_DEFAULTS)}
    return {'schema_version':1,'source_document_id':'synthetic','mode':'bpmn','notes':[],
            'pages':[{'id':'page','name':'BPMN collaboration','nodes':nodes,'relationships':[rel]}]}


@unittest.skipUnless(shutil.which('node'),'Node.js required')
class BpmnSafetyTests(unittest.TestCase):
    def setUp(self):
        self.document=bpmn_document()
        self.fixture={'packages':[{'guid':CAT,'name':'BPMN catalogue','elements':[
            {'guid':POOL,'name':'p','type':'ActivityPartition','stereotype':'BPMN2.0::Pool'},
            {'guid':LANE,'name':'lane','type':'ActivityPartition','stereotype':'BPMN2.0::Lane','parent_guid':POOL},
            {'guid':PROCESS,'name':'task','type':'Activity','stereotype':'BPMN2.0::Activity','parent_guid':LANE,'tags':{'activityType':'Task'}},
            {'guid':OTHER,'name':'task2','type':'Activity','stereotype':'BPMN2.0::Activity','parent_guid':LANE,'tags':{'activityType':'Task'}}]}],
            'connectors':[{'guid':CONNECTOR,'source':PROCESS,'target':OTHER,'name':'approved order',
                'type':'ControlFlow','stereotype':'BPMN2.0::SequenceFlow','direction':'Source -> Destination'}]}
        self.snapshot=export(self.fixture);self.profile=profile(self.snapshot)
        self.choices={key:{'action':'REUSE','master_guid':value} for key,value in [('p',POOL),('lane',LANE),('task',PROCESS),('task2',OTHER)]}
        self.relations={'flow':{'existing_connector_guid':CONNECTOR}}

    def plan(self, **kwargs): return build_plan(self.document,self.profile,self.snapshot,self.choices,self.relations,**kwargs)

    def test_pool_lane_activity_physical_reuse_preserves_parentage(self):
        plan=self.plan(mode='EXECUTE',execute_approved=True)
        self.assertTrue(plan['can_execute'],plan)
        out=run_js(generate_jscript(plan),self.fixture)
        self.assertIsNone(out['error'],out['logs'])
        self.assertEqual(len(out['elements']),4);self.assertEqual(len(out['connectors']),1)
        self.assertTrue(all(e['UpdateCalls']==0 for e in out['elements']))

    def test_wrong_lane_parent_in_snapshot_or_live_repository_is_blocked(self):
        self.snapshot['elements'][next(i for i,e in enumerate(self.snapshot['elements']) if e['guid']==LANE)]['parent_guid']=''
        self.assertFalse(self.plan()['can_execute'])
        self.snapshot=export(self.fixture)
        self.fixture['packages'][0]['elements'][1]['parent_guid']=''
        out=run_js(generate_jscript(self.plan(mode='EXECUTE',execute_approved=True)),self.fixture)
        self.assertIsNotNone(out['error']);self.assertEqual(out['mutationAttempts'],0)

    def test_sequence_flow_cross_pool_is_rejected_message_flow_is_accepted(self):
        source=self.document['pages'][0]['nodes'][2]
        target=copy.deepcopy(self.document['pages'][0]['nodes'][3]);target.update(pool='another-pool',process_scope='another-pool')
        relation=copy.deepcopy(self.document['pages'][0]['relationships'][0])
        self.assertIn('Pool',relation_error(source,target,relation))
        relation['relationship_type']='BPMN: Message Flow'
        self.assertIsNone(relation_error(source,target,relation))
        target.update(kind='gateway',ea_type='BPMN2.0::Gateway')
        self.assertIsNotNone(relation_error(source,target,relation))

    def test_cross_pool_invalid_plan_performs_no_writes(self):
        self.document['pages'][0]['nodes'][3].update(pool='other',process_scope='other')
        plan=self.plan(mode='EXECUTE',execute_approved=True)
        self.assertEqual(plan['relationships'][0]['action'],'BLOCK')
        out=run_js(generate_jscript(plan),self.fixture)
        self.assertEqual(out['mutationAttempts'],0);self.assertFalse(out['diagrams'])

    def test_sequence_subprocess_and_start_end_constraints(self):
        source,target=self.document['pages'][0]['nodes'][2:]
        r=self.document['pages'][0]['relationships'][0]
        target['process_scope']='subprocess';self.assertIsNotNone(relation_error(source,target,r))
        target['process_scope']='p';target.update(kind='start',ea_type='BPMN2.0::StartEvent')
        self.assertIsNotNone(relation_error(source,target,r))
        source.update(kind='end',ea_type='BPMN2.0::EndEvent');target.update(kind='task',ea_type='BPMN2.0::Activity')
        self.assertIsNotNone(relation_error(source,target,r))

    def test_data_association_is_not_sequence_flow_or_arbitrary_actor_link(self):
        source,target=self.document['pages'][0]['nodes'][2:]
        source.update(kind='data',ea_type='BPMN2.0::DataObject')
        r=self.document['pages'][0]['relationships'][0]
        self.assertIsNotNone(relation_error(source,target,r))
        r['relationship_type']='BPMN: Data Association';self.assertIsNone(relation_error(source,target,r))
        source['ea_type']='Actor';self.assertIsNotNone(relation_error(source,target,r))

    def test_missing_mdg_stops_before_creating_any_package(self):
        out=run_js(generate_jscript(self.plan(mode='EXECUTE',execute_approved=True)),{**self.fixture,'technologies':[]})
        self.assertIn('MDG',out['error']);self.assertEqual(out['mutationAttempts'],0)

    def test_message_flow_is_reused_between_distinct_participants_at_runtime(self):
        page=self.document['pages'][0];second_pool=copy.deepcopy(page['nodes'][0])
        second_pool.update(id='p2',source_element_id='p2',name='p2',pool='p2',process_scope='p2')
        page['nodes'].append(second_pool)
        page['nodes'][3].update(parent='p2',pool='p2',process_scope='p2')
        page['relationships'][0]['relationship_type']='BPMN: Message Flow'
        self.fixture['packages'][0]['elements'].append({'guid':CHILD,'name':'p2','type':'ActivityPartition','stereotype':'BPMN2.0::Pool'})
        self.fixture['packages'][0]['elements'][3]['parent_guid']=CHILD
        self.fixture['connectors'][0]['stereotype']='BPMN2.0::MessageFlow'
        self.choices['p2']={'action':'REUSE','master_guid':CHILD}
        self.snapshot=export(self.fixture)
        plan=self.plan(mode='EXECUTE',execute_approved=True)
        self.assertTrue(plan['can_execute'],plan)
        out=run_js(generate_jscript(plan),self.fixture)
        self.assertIsNone(out['error'],out['logs'])
        self.assertEqual(out['connectors'][0]['StereotypeEx'],'BPMN2.0::MessageFlow')

    def test_bpmn_reference_context_and_changed_tags_block_reuse(self):
        self.fixture['packages'][0]['elements'][0]['tags']={'processRef':PROCESS}
        self.snapshot=export(self.fixture)
        self.assertGreater(self.plan()['summary']['BLOCK'],0)
        self.fixture['packages'][0]['elements'][0]['tags']={};self.snapshot=export(self.fixture)
        self.fixture['packages'][0]['elements'][0]['tags']={'processRef':PROCESS}
        out=run_js(generate_jscript(self.plan(mode='EXECUTE',execute_approved=True)),self.fixture)
        self.assertIsNotNone(out['error']);self.assertEqual(out['mutationAttempts'],0)

    def test_public_bpmn_converter_uses_shared_runtime(self):
        from drawio_to_sparx import convert
        source=(ROOT/'examples/proses_sederhana.drawio').read_bytes()
        document=read_source(source,mode='bpmn')
        choices={n['id']:{'action':'NEW','approved_new':True} for p in document['pages'] for n in p['nodes']}
        relations={r['id']:{'semantic_confirmed':True,'approved_create':True,'relationship_type':
                   'BPMN: Data Association' if any(n['kind']=='data' and n['id'] in (r['source'],r['target']) for n in document['pages'][0]['nodes'])
                   else 'BPMN: Sequence Flow'} for p in document['pages'] for r in p['relationships']}
        script,_,_=convert(source,repository_profile=self.profile,snapshot=self.snapshot,element_decisions=choices,
            relationship_decisions=relations,execution_mode='EXECUTE',execute_approved=True)
        out=run_js(script,self.fixture)
        self.assertIsNone(out['error'],out['logs'])
        self.assertTrue(any(e['StereotypeEx']=='BPMN2.0::Activity' and not e.get('seeded') for e in out['elements']))

    def test_reader_preserves_explicit_message_flow_and_source_identity(self):
        source=b'''<mxfile><diagram id="page-a" name="Collaboration"><mxGraphModel><root>
        <mxCell id="0"/><mxCell id="1" parent="0"/>
        <mxCell id="p1" value="A" style="swimlane;" vertex="1" parent="1"><mxGeometry x="0" y="0" width="300" height="300" as="geometry"/></mxCell>
        <mxCell id="p2" value="B" style="swimlane;" vertex="1" parent="1"><mxGeometry x="400" y="0" width="300" height="300" as="geometry"/></mxCell>
        <mxCell id="a" value="Send" vertex="1" parent="p1"><mxGeometry x="50" y="50" width="100" height="50" as="geometry"/></mxCell>
        <mxCell id="b" value="Receive" vertex="1" parent="p2"><mxGeometry x="50" y="50" width="100" height="50" as="geometry"/></mxCell>
        <mxCell id="message" value="Request" style="messageFlow;" edge="1" source="a" target="b" parent="1"/>
        </root></mxGraphModel></diagram></mxfile>'''
        doc=read_source(source,mode='bpmn',document_id='OPCO-A/process-order')
        page=doc['pages'][0];r=page['relationships'][0]
        self.assertEqual(page['id'],'page-a')
        self.assertEqual(r['relationship_type'],'BPMN: Message Flow')
        self.assertEqual(len([n for n in page['nodes'] if n['kind']=='pool']),2)
        self.assertEqual({n['source_document_id'] for n in page['nodes']},{'OPCO-A/process-order'})


class MetadataAndMetamodelTests(unittest.TestCase):
    def test_profiles_are_whitelisted_and_production_defaults_are_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'profiles.json'
            profiles=load_profiles(path)
            self.assertFalse(profiles['Holding Production']['allow_new_elements'])
            profiles['Local Testing']['password']='do-not-store'
            save_profiles(profiles,path)
            self.assertNotIn('do-not-store',path.read_text())
            self.assertEqual(set(load_profiles(path)),{'Local Testing','Holding Production'})
        with self.assertRaises(ValueError):
            normalise_profile({'environment':'production','expected_identity':{'kind':'local','locator':'Z:/clone.qea'}})
        with self.assertRaises(ValueError):
            normalise_profile({'environment':'local','expected_identity':{'kind':'server','server':'holding','database':'ea','provider':'test'}})
        with self.assertRaises(ValueError): normalise_profile({'allow_new_elements':'false'})

    def test_archimate_supported_relationship_matrix_and_access_direction(self):
        def node(kind): return {'kind':'box','ea_type':archimate(kind)}
        def rel(kind,tags=None): return {'relationship_type':'ArchiMate: '+kind,'direction':'Source -> Destination','tags':tags or {}}
        for kind,source,target in [('Assignment','BusinessActor','BusinessRole'),('Serving','ApplicationService','BusinessProcess'),
                                   ('Realization','ApplicationFunction','ApplicationService'),('Flow','ApplicationComponent','ApplicationComponent'),
                                   ('Triggering','BusinessProcess','BusinessProcess'),('Association','BusinessActor','DataObject')]:
            with self.subTest(kind=kind): self.assertIsNone(relation_error(node(source),node(target),rel(kind)))
        self.assertIsNotNone(relation_error(node('DataObject'),node('BusinessActor'),rel('Assignment')))
        self.assertIsNotNone(relation_error(node('ApplicationComponent'),node('DataObject'),rel('Access')))
        self.assertIsNone(relation_error(node('ApplicationComponent'),node('DataObject'),rel('Access',{'accessType':'Read'})))
        self.assertIsNotNone(relation_error(node('DataObject'),node('ApplicationComponent'),rel('Access',{'accessType':'Read'})))

    def test_source_business_identifier_metadata_is_preserved(self):
        source=b'''<mxfile><diagram name="A"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>
        <object id="actor" label="Manager" BusinessID="ACT-001" OPCO="OPCO-A"><mxCell vertex="1" parent="1" style="shape=umlActor;">
        <mxGeometry x="0" y="0" width="60" height="100" as="geometry"/></mxCell></object>
        </root></mxGraphModel></diagram></mxfile>'''
        node=read_source(source)['pages'][0]['nodes'][0]
        self.assertEqual(node['business_id'],'ACT-001');self.assertEqual(node['opco'],'OPCO-A')

    def test_csv_remains_readable_but_cannot_authorize_runtime_reuse(self):
        from test_catalogue import catalog_csv
        snapshot=read_snapshot(catalog_csv())
        document=manager_document();elements,relations=decisions(document)
        plan=build_plan(document,{'catalogue_root_guid':CAT,'expected_identity':{'kind':'local','locator':'Z:/EA/testing.qea'}},
                        snapshot,elements,relations)
        self.assertFalse(plan['can_execute'])


if __name__=='__main__': unittest.main()
