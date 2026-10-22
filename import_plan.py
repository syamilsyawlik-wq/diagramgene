"""Repository-aware intermediate plan shared by existing Generic and BPMN readers.

A plan is data, not a write operation. Its decisions and approvals are rechecked by
runtime/importer.js against the active EA repository before the first AddNew.
"""
import copy
import hashlib
import json
from pathlib import Path

from ea_catalogue import guid, descendant_packages, type_matches, scoped_candidates, name_key
from repository_profiles import normalise_profile, boolean_option
from semantic_rules import BPMN_TYPES, BPMN_RELATIONS, relation_error, node_error
from model_types import RELATION_TYPES, EA_ELEMENT_TYPES

ROOT = Path(__file__).resolve().parent
EMPTY_TEXT_HASH = hashlib.sha256(b'').hexdigest()
END_DEFAULTS = {'Role':'','Cardinality':'','Aggregation':0,'Navigable':'Unspecified','RoleType':'',
                'Alias':'','Qualifier':'','Containment':'Unspecified','Visibility':'Public','Derived':False,'Ordering':0,
                'role_note_hash':EMPTY_TEXT_HASH}


def canonical(value):
    def ordered(item):
        if isinstance(item, dict):
            return {key:ordered(item[key]) for key in sorted(item,key=lambda k:k.encode('utf-16-be'))}
        if isinstance(item, list): return [ordered(v) for v in item]
        return item
    return json.dumps(ordered(value), ensure_ascii=False, allow_nan=False, separators=(',',':')).replace('\u2028','\\u2028').replace('\u2029','\\u2029')


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def read_source(source, mode='generic', profile='uml', default_type=None, document_id=None):
    # Reuse the existing XML/embedded PNG/SVG and Visio readers. No image/OCR path.
    from generic_mode import load_generic_pages
    from drawio_to_sparx import classify, parse_style
    raw=bytes(source) if isinstance(source,(bytes,bytearray)) else Path(source).read_bytes()
    doc_id=document_id or hashlib.sha256(raw).hexdigest()
    pages,notes=load_generic_pages(raw,default_type=default_type,profile=profile)
    normalized=[];seen_pages=set()
    for ordinal,page in enumerate(pages):
        page_id=page.get('source_page_id') or 'page-'+str(ordinal+1)
        if page_id in seen_pages: raise ValueError('Source Page ID duplikat; perbaiki identitas halaman sumber.')
        seen_pages.add(page_id)
        nodes=[]
        for item in page['items']:
            metadata=item.get('source_metadata',{})
            node={'id':page_id+'/'+item['key'],'source_document_id':doc_id,'source_page_id':page_id,
                  'source_element_id':item['key'],'name':item['text'],'original_shape':item.get('source_style',''),
                  'ea_type':item['ea_type'],'kind':item['kind'],'parent':None,'pool':None,'process_scope':None,
                  'geometry':{k:int(round(item[k])) for k in ('l','t','r','b')},
                  'business_id':metadata.get('DG_BusinessID') or metadata.get('BusinessID',''),
                  'opco':metadata.get('DG_OPCO') or metadata.get('OPCO',''),'source_master_guid':metadata.get('MasterGUID',''),
                  'scope_package_guid':'','inferred':item.get('mapping_basis') not in ('jenis bentuk','bentuk sumber')}
            nodes.append(node)
        by_source={n['source_element_id']:n for n in nodes}
        if mode=='bpmn':
            for node in nodes:
                if 'subprocess' in node['original_shape'].lower() or 'sub-process' in node['original_shape'].lower():
                    node['kind']='container'
        containers=[n for n in nodes if n['kind']=='container']
        def parent_of(node):
            g=node['geometry']
            candidates=[c for c in containers if c is not node and c['geometry']['l']<=g['l'] and c['geometry']['t']<=g['t']
                        and g['r']<=c['geometry']['r'] and g['b']<=c['geometry']['b']
                        and (c['geometry']['r']-c['geometry']['l'])*(c['geometry']['b']-c['geometry']['t'])>
                            (g['r']-g['l'])*(g['b']-g['t'])]
            explicit=next((i.get('source_parent') for i in page['items'] if i['key']==node['source_element_id']),None)
            if explicit in by_source and by_source[explicit] in containers: return by_source[explicit]
            return min(candidates,key=lambda c:(c['geometry']['r']-c['geometry']['l'])*(c['geometry']['b']-c['geometry']['t']),default=None)
        for node in nodes:
            par=parent_of(node);node['parent']=par['id'] if par else None
        if mode=='bpmn':
            for node in containers:
                style=node['original_shape'].lower()
                if node['kind']=='gateway':
                    properties=parse_style(style)[1]
                    value=properties.get('gatewaytype') or properties.get('gwtype') or 'exclusive'
                    node['gateway_type']={'exclusive':'Exclusive','parallel':'Parallel','inclusive':'Inclusive'}.get(value,value)
                visio_name=parse_style(style)[1].get('semantic','')
                node['kind']='subprocess' if 'subprocess' in style or 'sub-process' in style else ('lane' if node['parent'] or any(t in visio_name for t in ('functional band','swimlane','lane')) else 'pool')
                node['ea_type']=BPMN_TYPES[node['kind']]
            pools=[n for n in nodes if n['kind']=='pool']
            if not pools:
                bounds={'l':min(n['geometry']['l'] for n in nodes)-40,'t':min(n['geometry']['t'] for n in nodes)-40,
                        'r':max(n['geometry']['r'] for n in nodes)+40,'b':max(n['geometry']['b'] for n in nodes)+40}
                pool={'id':page_id+'/__pool__','source_document_id':doc_id,'source_page_id':page_id,'source_element_id':'__pool__',
                      'name':page['name'],'kind':'pool','ea_type':BPMN_TYPES['pool'],'parent':None,'pool':None,'process_scope':None,
                      'geometry':bounds,'business_id':'','opco':'','scope_package_guid':'','inferred':True,'original_shape':'synthetic pool'}
                nodes.insert(0,pool);pools=[pool]
            index={n['id']:n for n in nodes}
            for node in nodes:
                if node['kind']=='note': node['kind']='annotation'
                if node['kind'] not in ('pool','lane','subprocess','actor','text','annotation'):
                    _,properties=parse_style(node['original_shape'])
                    kind=classify('shape='+properties['semantic']) if properties.get('semantic') else classify(node['original_shape'])
                    node['kind']={'event':'event','gateway':'gateway','data':'data','link':'link'}.get(kind,'task')
                if node['kind'] not in ('pool','actor','text') and not node['parent'] and len(pools)==1:
                    node['parent']=pools[0]['id']
                current=node;ancestry=[]
                while current:
                    if current['id'] in ancestry: raise ValueError('Siklus parent sumber.')
                    ancestry.append(current['id']);current=index.get(current.get('parent'))
                node['pool']=next((key for key in ancestry if index[key]['kind']=='pool'),None)
                node['process_scope']=next((key for key in ancestry[1:] if index[key]['kind'] in ('subprocess','pool')),node['pool'])
            incoming={n['id']:0 for n in nodes};outgoing=incoming.copy()
            for link in page['links']:
                marker=link.get('source_style','').lower().replace('_','').replace(' ','')
                if any(t in marker for t in ('messageflow','dataassociation','bpmnassociation')): continue
                outgoing[by_source[link['src']]['id']]+=1;incoming[by_source[link['tgt']]['id']]+=1
            for node in nodes:
                if node['kind']=='event':
                    style=node['original_shape'].lower()
                    node['kind']='start' if any(k in style for k in ('startevent','startstate','start_1','start_2')) else 'end' if any(k in style for k in ('endevent','endstate')) else 'start' if incoming[node['id']]==0 else 'end' if outgoing[node['id']]==0 else 'link'
                if node['kind'] in BPMN_TYPES: node['ea_type']=BPMN_TYPES[node['kind']]
                style=node['original_shape'].lower()
                if 'message' in style: node['event_definition']='Message'
                node['event_direction']='catch' if node['kind']=='start' or 'catch' in style else 'throw' if node['kind']=='end' or 'throw' in style else ''
        relationships=[]
        for link in page['links']:
            style=link.get('source_style','').lower()
            kind=link['relation_type'];confirmed=False
            if mode=='bpmn':
                explicit=next((label for token,label in [('messageflow','BPMN: Message Flow'),('sequenceflow','BPMN: Sequence Flow'),
                    ('dataassociation','BPMN: Data Association'),('bpmnassociation','BPMN: Association')] if token in style.replace('_','').replace(' ','')),None)
                kind=explicit or 'BPMN: Sequence Flow';confirmed=bool(explicit)
            relationships.append({'id':page_id+'/'+link['key'],'source_relationship_id':link['key'],
                'source':by_source[link['src']]['id'],'target':by_source[link['tgt']]['id'],'name':link['name'],
                'relationship_type':kind,'direction':link['direction'],'semantic_confirmed':confirmed,
                'endpoint_basis':link.get('endpoint_basis','explicit'),
                'tags':{},'source_role':dict(END_DEFAULTS),'target_role':dict(END_DEFAULTS)})
        normalized.append({'id':page_id,'name':page['name'],'nodes':nodes,'relationships':relationships,
                           'unresolved_relationships':page.get('unresolved_relationships',[])})
    return {'schema_version':1,'source_document_id':doc_id,'mode':mode,'pages':normalized,'notes':notes}


def connector_signature(c):
    return {k:c.get(k) for k in ('source_guid','target_guid','base_type','stereotype','name','direction','source_role','target_role','tags_hash','notes_hash')}


def propose_decisions(document,profile,snapshot):
    """Proposals never grant NEW/relationship/EXECUTE approval.

    A unique name is insufficient: require explicit source shape semantics,
    verified catalogue type/stereotype, scope and (for BPMN) owning context.
    """
    snapshot=snapshot or {};profile=normalise_profile(profile)
    scope=descendant_packages(snapshot,profile['scope_package_guid'] or profile['catalogue_root_guid'])
    entries=snapshot.get('elements',[]);result={}
    for page in document['pages']:
        for node in page['nodes']:
            candidates,alias_only=scoped_candidates(entries,node,scope,profile['opco'] or node.get('opco',''))
            has_context_candidate=bool(candidates)
            conflicting_metadata=any(e.get('package_guid') in scope and e.get('metadata_status')=='NEEDS_REVIEW'
                and (name_key(e['name'])==name_key(node['name']) or node.get('business_id') and e.get('business_id')==node['business_id'])
                for e in entries)
            parent=result.get(node.get('parent'),{})
            if node['ea_type'].startswith('BPMN2.0::') and node.get('parent'):
                candidates=[e for e in candidates if parent.get('master_guid') and e.get('parent_guid')==parent['master_guid']]
            known=not node.get('inferred',True)
            if node.get('source_master_guid'):
                result[node['id']]={'action':'REUSE','master_guid':node['source_master_guid'],'proposal_reason':'GUID master eksplisit dari metadata sumber; wajib lolos preflight.'}
            elif known and len(candidates)==1 and not alias_only and not candidates[0].get('legacy') and candidates[0].get('metadata_status')!='NEEDS_REVIEW':
                result[node['id']]={'action':'REUSE','master_guid':candidates[0]['guid'],'proposal_reason':'Bentuk/tipe sumber eksplisit, tipe/stereotype katalog dan scope cocok; satu kandidat.'}
            elif known and not candidates and not has_context_candidate and not conflicting_metadata and snapshot.get('schema_version')==2 and profile['allow_new_elements'] and node['ea_type'] not in document.get('required_master_types',[]):
                result[node['id']]={'action':'NEW','master_guid':'','approved_new':False,'proposal_reason':'Tipe sumber eksplisit; master sesuai scope tidak ditemukan. NEW belum disetujui.'}
            else:
                result[node['id']]={'action':'REVIEW','master_guid':'','proposal_reason':'Perlu review: semantik belum pasti, alias, metadata tidak lengkap, atau kandidat ambigu.'}
    return result


def build_plan(document, profile, snapshot=None, element_decisions=None, relationship_decisions=None,
               mode='VALIDATE_ONLY', execute_approved=False):
    profile=normalise_profile(profile);snapshot=snapshot or {}
    if type(execute_approved) is not bool: raise ValueError('execute_approved harus boolean.')
    if mode not in ('VALIDATE_ONLY','EXECUTE'): raise ValueError('Mode eksekusi tidak dikenal.')
    plan={'schema_version':1,'document_id':document['source_document_id'],'mode':mode,'profile':profile,
          'snapshot_at':snapshot.get('exported_at',''),'nodes':[],'relationships':[],'pages':[],
          'errors':[],'required_technologies':[]}
    source=snapshot.get('repository_source')
    if source:
        plan['repository_source']=copy.deepcopy(source)
        if source.get('trusted_capture'):
            if profile['environment']!='local': plan['errors'].append('Capture QEA lokal tidak memberi izin EXECUTE ke repository production.')
            if not profile['qea_identity_reviewed']:
                plan['errors'].append('Lokasi repository menurut EA/Wine belum direview. Path bukan identitas unik global.')
            from qea_reader import probe, QEAError
            try:
                if probe(source['backend_path'])['fingerprint']!=source['fingerprint']:
                    plan['errors'].append('QEA berubah sejak capture; segarkan dan review ulang.')
            except QEAError as exc: plan['errors'].append(str(exc))
    if not profile['expected_identity']: plan['errors'].append('Expected repository identity belum diverifikasi/diisi dari snapshot.')
    if snapshot.get('repository_identity') and snapshot['repository_identity']!=profile['expected_identity']:
        plan['errors'].append('Identity snapshot berbeda dari profile repository.')
    if profile['environment']=='production' and snapshot.get('schema_version')!=2:
        plan['errors'].append('Production memerlukan snapshot v2, bukan CSV legacy.')
    if profile['environment']=='production' and not profile['opco'] and not profile['scope_package_guid']:
        plan['errors'].append('Production memerlukan scope package atau OPCO eksplisit.')
    if snapshot and profile['catalogue_root_guid']!=snapshot.get('package_guid'):
        plan['errors'].append('Root katalog snapshot berbeda dari profile.')
    if snapshot.get('schema_version')==2 and profile['scope_package_guid'] and profile['scope_package_guid'] not in descendant_packages(snapshot,profile['catalogue_root_guid']):
        plan['errors'].append('Scope package berada di luar katalog.')
    entries=snapshot.get('elements',[]);by_guid={e['guid']:e for e in entries}
    scope=descendant_packages(snapshot,profile['scope_package_guid'] or profile['catalogue_root_guid'])
    decisions=element_decisions or {};rdecisions=relationship_decisions or {}
    for page in document['pages']:
        if page.get('unresolved_relationships'):
            plan['errors'].append(page['name']+': endpoint source relationship belum dapat di-resolve: '+', '.join(r['id'] for r in page['unresolved_relationships']))
        plan['pages'].append({'id':page['id'],'name':page['name'],'diagram_type':'BPMN2.0::Business Process' if document['mode']=='bpmn' else 'Custom'})
        for source in page['nodes']:
            node=copy.deepcopy(source);choice=decisions.get(node['id'],{})
            node.update(ea_type=choice.get('ea_type',node['ea_type']),action=choice.get('action','REVIEW'),
                        master_guid=choice.get('master_guid',node.get('source_master_guid','')),approved_new=boolean_option(choice,'approved_new'),
                        same_master_confirmed=boolean_option(choice,'same_master_confirmed'),
                        distinct_object_confirmed=boolean_option(choice,'distinct_object_confirmed'),
                        qualified_package_path=choice.get('qualified_package_path',''))
            if node['ea_type'] not in EA_ELEMENT_TYPES: raise ValueError('Semantic type tidak didukung.')
            node['requires_master']=node['ea_type'] in document.get('required_master_types',[])
            if node['ea_type'].startswith('BPMN2.0::'):
                kinds=[k for k,t in BPMN_TYPES.items() if t==node['ea_type']]
                if node['kind'] not in kinds: node['kind']=kinds[0]
            if choice.get('business_id'): node['business_id']=choice['business_id']
            if node.get('opco') and profile['opco'] and node['opco']!=profile['opco']:
                plan['errors'].append(node['id']+': OPCO sumber berbeda dari profile.')
            for field in ('event_definition','event_direction','gateway_type'):
                if field in choice and choice[field]: node[field]=choice[field]
            node['status']='REVIEW';node['reason']='Pilih reuse/new dan konfirmasi makna elemen.';node['master']=None
            geometry=node['geometry']
            if any(type(geometry.get(k)) is not int for k in ('l','t','r','b')) or geometry['l']>=geometry['r'] or geometry['t']>=geometry['b']:
                plan['errors'].append(node['id']+': geometry sumber tidak valid.')
            node['resolution_basis']='guid' if node['master_guid'] else 'business_id' if node.get('business_id') else 'name'
            effective_opco=profile['opco'] or node.get('opco','')
            candidates,alias_only=scoped_candidates(entries,node,scope,effective_opco)
            node['candidates']=[{'guid':e['guid'],'name':e['name'],'alias':e.get('alias',''),'package_path':e.get('package_path',''),'ea_type':e.get('ea_type','')} for e in candidates]
            if node['master_guid']:
                node['master_guid']=guid(node['master_guid']);master=by_guid.get(node['master_guid'])
                if not master: node.update(status='BLOCK',reason='GUID master tidak ditemukan dalam snapshot katalog.')
                elif master.get('package_guid') not in scope: node.update(status='BLOCK',reason='Master berada di luar scope package.')
                elif not type_matches(master,node['ea_type']): node.update(status='BLOCK',reason='Base type / qualified stereotype master berbeda.')
                elif effective_opco and master.get('opco')!=effective_opco: node.update(status='BLOCK',reason='OPCO master berbeda atau tidak terverifikasi.')
                elif node.get('business_id') and master.get('business_id')!=node['business_id']: node.update(status='BLOCK',reason='Stable business identifier master berbeda.')
                elif node['qualified_package_path'] and master.get('package_path')!=node['qualified_package_path']: node.update(status='BLOCK',reason='Qualified package identity master berbeda.')
                elif master.get('legacy'): node.update(status='REVIEW',reason='CSV legacy belum memuat identity/parent/base type yang cukup untuk execute.')
                elif master.get('metadata_status')=='NEEDS_REVIEW': node.update(status='BLOCK',reason='Metadata repository belum terverifikasi: '+'; '.join(master.get('metadata_reasons',[])))
                elif node['action']=='REUSE': node.update(status='REUSE',reason='GUID dan tipe/scope cocok; runtime wajib memvalidasi ulang.',master=copy.deepcopy(master))
            elif node['action']=='REUSE':
                if len(candidates)!=1 or alias_only: node.update(status='BLOCK',reason='Master ambigu/tidak ditemukan atau hanya alias; pilih GUID eksplisit.')
                else:
                    master=candidates[0]
                    if master.get('legacy'): node.update(status='REVIEW',reason='Ekspor snapshot v2 untuk validasi runtime.')
                    elif master.get('metadata_status')=='NEEDS_REVIEW': node.update(status='BLOCK',reason='Metadata repository memerlukan review native; tidak akan diasumsikan kompatibel.')
                    else: node.update(status='REUSE',reason='Identitas bisnis atau exact name/type/scope dikonfirmasi.',master_guid=master['guid'],master=copy.deepcopy(master))
            elif node['action']=='NEW':
                if node.get('requires_master'): node.update(status='BLOCK',reason='Tipe ini wajib memakai master katalog; buat master terpisah di EA lalu ekspor ulang.')
                elif not profile['allow_new_elements']: node.update(status='BLOCK',reason='Profile melarang elemen baru.')
                elif candidates and not node['distinct_object_confirmed']: node.update(status='REVIEW',reason='Kandidat master tersedia. Reuse atau konfirmasikan objek berbeda sebelum NEW.')
                elif not node['approved_new']: node.update(status='REVIEW',reason='Pembuatan elemen baru belum disetujui per elemen.')
                else: node.update(status='NEW',reason='Elemen lokal baru disetujui; tidak mengubah master existing.')
            plan['nodes'].append(node)
    nodes={n['id']:n for n in plan['nodes']}
    collisions={}
    for node in plan['nodes']:
        if node['status']=='REUSE': collisions.setdefault((node['source_page_id'],node['master_guid']),[]).append(node)
        if node['kind'] in ('lane','task','subprocess','gateway','start','end','link','data','annotation') and node['ea_type'].startswith('BPMN2.0::'):
            parent=nodes.get(node.get('parent'))
            if not parent or parent['kind'] not in ('pool','lane','subprocess'):
                node.update(status='BLOCK',reason='Parent BPMN tidak valid/di luar representasi yang didukung.')
            elif node['status']=='REUSE' and (parent['status']!='REUSE' or node['master'].get('parent_guid')!=parent['master_guid']):
                node.update(status='BLOCK',reason='Parent Pool/Lane/subprocess master berbeda; tidak akan dipindah/reparent.')
        if node['kind']=='pool' and node['status']=='REUSE' and node['master'].get('parent_guid'):
            node.update(status='BLOCK',reason='Pool dengan owning process element memerlukan context/reference BPMN yang belum didukung.')
        semantic_error=node_error(node)
        if semantic_error: node.update(status='BLOCK',reason=semantic_error)
        if '::' in node['ea_type']:
            technology=node['ea_type'].split('::')[0]
            if technology not in plan['required_technologies']: plan['required_technologies'].append(technology)
    for same in collisions.values():
        if len(same)>1 and not all(n['same_master_confirmed'] for n in same):
            for node in same: node.update(status='BLOCK',reason='Dua source object berbeda dipetakan ke satu master pada halaman yang sama; konfirmasi referensi yang sama secara eksplisit.')
    relation_types={**RELATION_TYPES,**BPMN_RELATIONS}
    for page in document['pages']:
        for original in page['relationships']:
            r=copy.deepcopy(original);choice=rdecisions.get(r['id'],{})
            for key in ('relationship_type','direction','tags','source_role','target_role','semantic_confirmed','name'):
                if key in choice: r[key]=choice[key]
            if not isinstance(r.get('tags'),dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in r['tags'].items()):
                raise ValueError('Relationship tagged values harus berupa pasangan string.')
            for field in ('source_role','target_role'):
                values=r.get(field,{})
                if not isinstance(values,dict) or set(values)-set(END_DEFAULTS): raise ValueError('Role properties connector tidak didukung.')
                r[field]={**END_DEFAULTS,**values}
                if any(type(value) is not type(END_DEFAULTS[key]) for key,value in r[field].items()):
                    raise ValueError('Tipe nilai role properties connector tidak valid.')
            if profile['environment']=='production' and 'semantic_confirmed' not in choice:
                r['semantic_confirmed']=False  # Source notation is not production approval.
            r['semantic_confirmed']=boolean_option(r,'semantic_confirmed')
            r.update(action='REVIEW',reason='',existing_connector_guid=choice.get('existing_connector_guid',''),
                     approved_create=boolean_option(choice,'approved_create'),accept_existing_properties=boolean_option(choice,'accept_existing_properties'),expected_connector=None)
            r['notes_hash']=EMPTY_TEXT_HASH
            r['source_guid']=nodes[r['source']].get('master_guid','');r['target_guid']=nodes[r['target']].get('master_guid','')
            if r['relationship_type']=='Realization': r['relationship_type']='Realisation'
            if r['relationship_type'] not in relation_types:
                r.update(action='BLOCK',reason='Tipe connector tidak didukung.');plan['relationships'].append(r);continue
            r['base_type'],r['stereotype']=relation_types[r['relationship_type']]
            error=relation_error(nodes[r['source']],nodes[r['target']],r)
            if error: r.update(action='BLOCK',reason=error)
            elif any(nodes[key]['status'] not in ('NEW','REUSE') for key in (r['source'],r['target'])):
                r.update(action='BLOCK',reason='Endpoint unresolved/ambigu; relasi tidak boleh dibuat.')
            elif r['source_guid'] and r['source_guid']==r['target_guid'] and r['source']!=r['target']:
                r.update(action='BLOCK',reason='Endpoint source berbeda terlipat ke master yang sama; relasi perlu review.')
            elif not r.get('semantic_confirmed'):
                r.update(action='REVIEW',reason='Makna relasi belum dikonfirmasi; geometri panah bukan bukti semantik.')
            else:
                tags=sorted([[str(k),str(v)] for k,v in r['tags'].items()],key=lambda item:canonical(item).encode('utf-16-be'))
                desired={**r,'tags_hash':hashlib.sha256(canonical(tags).encode()).hexdigest()}
                candidates=[c for c in snapshot.get('connectors',[]) if c.get('metadata_complete') and connector_signature(c)==connector_signature(desired)]
                core=('source_guid','target_guid','base_type','stereotype','name','direction')
                related=[c for c in snapshot.get('connectors',[]) if all(c.get(k)==r.get(k) for k in core)]
                uncertain=[c for c in snapshot.get('connectors',[]) if not c.get('metadata_complete') and
                    {c.get('source_guid'),c.get('target_guid')}=={r['source_guid'],r['target_guid']}]
                r['candidate_connector_guids']=[c['guid'] for c in related]
                if r['existing_connector_guid']:
                    selected=next((c for c in snapshot.get('connectors',[]) if c['guid']==guid(r['existing_connector_guid'])),None)
                    if not selected or not selected.get('metadata_complete') or any(selected.get(k)!=r.get(k) for k in core):
                        r.update(action='BLOCK',reason='Connector GUID salah/semantik endpoint, tipe, nama, atau arah tidak cocok.')
                    elif r['relationship_type']=='ArchiMate: Access' and (selected.get('semantic_tags',{}).get('accessType')!=r['tags'].get('accessType')):
                        r.update(action='BLOCK',reason='Access mode connector master berbeda/tidak terverifikasi; accept properties tidak dapat melewati konflik ini.')
                    elif connector_signature(selected)!=connector_signature(desired) and not r['accept_existing_properties']:
                        r.update(action='REVIEW',reason='Tagged values / role properties berbeda; periksa di EA dan konfirmasi properti existing.')
                    else: r.update(action='REUSE',reason='Connector GUID dan seluruh metadata yang didukung dikonfirmasi.',expected_connector=copy.deepcopy(selected))
                elif len(candidates)>1: r.update(action='REVIEW',reason='Beberapa connector semantik identik; pilih ConnectorGUID.')
                elif len(candidates)==1 and (r['name'] or r.get('meaning')):
                    r.update(action='REUSE',reason='Seluruh signature semantik cocok.',existing_connector_guid=candidates[0]['guid'],expected_connector=copy.deepcopy(candidates[0]))
                elif candidates: r.update(action='REVIEW',reason='Relasi tanpa nama/meaning memerlukan pemilihan ConnectorGUID eksplisit.')
                elif related: r.update(action='REVIEW',reason='Connector dengan makna inti sama mempunyai metadata role/tag berbeda/tidak lengkap; pilih GUID dan review di EA.')
                elif uncertain: r.update(action='REVIEW',reason='Endpoint mempunyai connector dengan metadata belum terverifikasi. Lengkapi katalog melalui exporter/native review sebelum mengusulkan relasi baru.')
                else: r.update(action='PROPOSE_CREATE',reason='Tidak ada connector setara; butuh persetujuan per relasi.')
            plan['relationships'].append(r)
            if r['action']=='PROPOSE_CREATE' and any(r[field]['role_note_hash']!=EMPTY_TEXT_HASH for field in ('source_role','target_role')):
                r.update(action='BLOCK',reason='Pembuatan role note baru belum didukung; jangan mengirim fingerprint sebagai properti EA.')
    # One explicitly named, equivalent proposal may appear on several pages.
    # Use master identities (or distinct source identities for NEW endpoints).
    proposed={};relation_by_id={r['id']:r for r in plan['relationships']}
    for r in plan['relationships']:
        if r['action']!='PROPOSE_CREATE': continue
        signature=connector_signature({**r,'tags_hash':fingerprint(sorted([[str(k),str(v)] for k,v in r['tags'].items()],key=lambda item:canonical(item).encode('utf-16-be')))})
        signature['source_guid']=r['source_guid'] or r['source']
        signature['target_guid']=r['target_guid'] or r['target']
        key=canonical(signature)
        if key in proposed and r['name']: r['reuse_planned_relation']=proposed[key]
        elif key in proposed:
            for unresolved in (r,relation_by_id[proposed[key]]):
                unresolved.update(action='REVIEW',reason='Proposal connector tanpa nama/meaning identik lebih dari satu; tentukan meaning atau pilih ConnectorGUID, jangan duplikasi/merge diam-diam.')
        else: proposed[key]=r['id']
    plan['summary']={k:sum(n['status']==k for n in plan['nodes']) for k in ('NEW','REUSE','REVIEW','BLOCK')}
    plan['relationship_summary']={k:sum(r['action']==k for r in plan['relationships']) for k in ('REUSE','PROPOSE_CREATE','REVIEW','BLOCK')}
    plan['can_execute']=not plan['errors'] and all(n['status'] in ('NEW','REUSE') for n in plan['nodes']) and all(
        r['action']=='REUSE' or r['action']=='PROPOSE_CREATE' and r['approved_create'] for r in plan['relationships'])
    plan['plan_digest']=fingerprint(plan)
    plan['approval_digest']=plan['plan_digest'] if execute_approved else ''
    return plan


def generate_jscript(plan):
    helpers='\n'.join((ROOT/name).read_text(encoding='utf-8') for name in
        ('runtime/metadata.js','runtime/repository_identity.js','runtime/importer.js'))
    return '// DiagramGene repository-aware import; self-contained ES3 JScript.\nvar PLAN = '+json.dumps(plan,ensure_ascii=True)+';\n'+helpers


def preview_pages(plan):
    result=[]
    for page in plan['pages']:
        nodes=[n for n in plan['nodes'] if n['source_page_id']==page['id']]
        items=[{'key':n['id'],'kind':'container' if n['kind'] in ('pool','lane','subprocess','container') else 'ellipse' if n['kind'] in ('start','end','link') else n['kind'] if n['kind'] in ('text','note','ellipse','diamond') else 'box',
                'text':n['name'],'ea_type':n['ea_type'],'seq':100 if n['kind']=='pool' else 50 if n['kind']=='lane' else 1,**n['geometry']} for n in nodes]
        links=[{'src':r['source'],'tgt':r['target'],'directed':r['direction']!='Unspecified','name':r['name']} for r in plan['relationships'] if r['source'] in {n['id'] for n in nodes}]
        result.append({'mode':'generic','name':page['name'],'title':page['name'],'items':items,'links':links,'skipped':[],
                       'pool':{'name':page['name']},'nodes':[],'lanes':[],'flows':[]})
    return result


def apply_layout(document, orient='vertical', keep_layout=False):
    if keep_layout or document['mode']!='bpmn': return document
    from drawio_to_sparx import auto_layout
    for page in document['pages']:
        pools=[n for n in page['nodes'] if n['kind']=='pool']
        if len(pools)!=1 or any(n['kind'] in ('subprocess','actor','text','note') for n in page['nodes']):
            document['notes'].append(page['name']+': layout sumber dipertahankan untuk collaboration/subprocess/annotation.')
            continue
        pool=pools[0];lanes=[n for n in page['nodes'] if n['kind']=='lane']
        layout_lanes=[{'key':n['id'],'name':n['name'],**n['geometry']} for n in lanes] or [{'key':'__layout_lane__','name':pool['name'],**pool['geometry']}]
        nodes=[{'key':n['id'],'kind':n['kind'],'name':n['name'],'lane':n['parent'] if any(l['key']==n['parent'] for l in layout_lanes) else layout_lanes[0]['key'],**n['geometry']}
               for n in page['nodes'] if n['kind'] not in ('pool','lane')]
        if not nodes: continue
        scene={'pool':{'name':pool['name'],**pool['geometry']},'lanes':layout_lanes,'nodes':nodes,'native_orient':orient,
               'flows':[{'src':r['source'],'tgt':r['target'],'kind':'seq' if r['relationship_type']=='BPMN: Sequence Flow' else 'data','name':r['name']}
                        for r in page['relationships'] if r['relationship_type'] in ('BPMN: Sequence Flow','BPMN: Data Association')]}
        scene=auto_layout(scene,orient)
        pool['geometry']={k:scene['pool'][k] for k in ('l','t','r','b')}
        positions={n['key']:n for n in scene['nodes']+scene['lanes']}
        for node in page['nodes']:
            if node['id'] in positions: node['geometry']={k:positions[node['id']][k] for k in ('l','t','r','b')}
    return document
