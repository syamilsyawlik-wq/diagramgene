"""Small native Streamlit review widgets for repository-aware import plans."""
import copy
import hashlib
import json
import streamlit as st
from import_plan import read_source, apply_layout, build_plan, generate_jscript, fingerprint, propose_decisions
from model_types import EA_TYPE_LABELS, EA_LABEL_TYPES, RELATION_TYPES


def profile_controls():
    from repository_inspector import repository_controls
    return repository_controls()


def review_plan(raw,mode,profile_context,chosen,default_type='Class',semantic_profile='uml',
                element_types=None,relation_types=None,catalogue=None,catalogue_data=None,orient='vertical',keep_layout=True):
    """Return governed script and a complete plan, without any EA connection."""
    profile=copy.deepcopy(profile_context['profile'])
    snapshot=profile_context.get('snapshot') or catalogue_data
    if catalogue and not profile['catalogue_root_guid']: profile['catalogue_root_guid']=catalogue['package_guid']
    with st.expander('Identitas dokumen sumber (opsional)'):
        document_id=st.text_input('Source Document ID stabil dari OPCO (kosong: hash file)',key='source_document_'+hashlib.sha256(raw).hexdigest()[:16])
    document=read_source(raw,mode=mode,profile=semantic_profile,default_type=default_type,document_id=document_id or None)
    document['required_master_types']=(catalogue or {}).get('managed_types',[])
    apply_layout(document,orient,keep_layout)
    document['pages']=[p for p in document['pages'] if p['name'] in chosen]
    if not document['pages']: raise ValueError('Tidak ada halaman sumber dipilih.')
    ebase={};rbase={}
    for page in document['pages']:
        for node in page['nodes']:
            overrides=(element_types or {}).get(page['name'],{})
            if node['source_element_id'] in overrides: node['ea_type']=overrides[node['source_element_id']]
            bound=(catalogue or {}).get('bindings',{}).get(page['name'],{}).get(node['source_element_id'],'') or node.get('source_master_guid','')
            ebase[node['id']]={'action':'REUSE' if bound else 'REVIEW','master_guid':bound,'ea_type':node['ea_type']}
        for rel in page['relationships']:
            selected=(relation_types or {}).get(page['name'],{}).get(rel['source_relationship_id'])
            if selected: rel['relationship_type']=selected
    proposals=propose_decisions(document,profile,snapshot)
    for node_id,decision in ebase.items():
        if decision['master_guid']: proposals[node_id]=decision
    ebase=proposals
    initial=build_plan(document,profile,snapshot,ebase,rbase)
    key=hashlib.sha256(raw+json.dumps([profile,chosen,document_id,element_types,relation_types,fingerprint(snapshot)],sort_keys=True).encode()).hexdigest()[:16]
    st.subheader('Review impor repository-aware')
    st.caption('Identitas sumber berbeda dari identitas master. Kandidat bukan keputusan reuse. NEW tidak melakukan merge berdasarkan nama.')
    rows=[]
    advanced=st.checkbox('Tampilkan kolom identitas dan semantik lanjutan',key='advanced_'+key)
    for n in initial['nodes']:
        rows.append({'Source ID':n['id'],'Source Element':n['name'],'Inferred Type':EA_TYPE_LABELS.get(n['ea_type'],n['ea_type']),
            'Semantic Type':EA_TYPE_LABELS.get(n['ea_type'],n['ea_type']),'Master GUID':n['master_guid'],
            'Business ID':n.get('business_id',''),'Qualified package path':'','Action':n['action'],'Approve NEW':False,'Distinct object confirmed':False,'Same master confirmed':False,
            'Event definition':n.get('event_definition',''),'Event direction':n.get('event_direction',''),'Gateway type':n.get('gateway_type',''),
            'Proposal reason':ebase.get(n['id'],{}).get('proposal_reason',''),
            'Candidates':' | '.join(c['guid']+' '+c['name']+' '+c.get('package_path','') for c in n['candidates'])})
    edited=st.data_editor(rows,hide_index=True,disabled=['Source ID','Source Element','Inferred Type','Candidates','Proposal reason'],
        column_order=None if advanced else ['Source Element','Inferred Type','Semantic Type','Master GUID','Action','Approve NEW','Proposal reason','Candidates'],
        column_config={'Source Element':'Elemen sumber','Inferred Type':'Tipe sumber','Master GUID':'GUID master',
                       'Proposal reason':'Alasan usulan','Approve NEW':'Setujui objek baru','Candidates':'Kandidat katalog',
                       'Action':st.column_config.SelectboxColumn('Keputusan',options=['REVIEW','REUSE','NEW'],required=True),
                       'Semantic Type':st.column_config.SelectboxColumn('Tipe EA usulan',options=list(EA_LABEL_TYPES),required=True),
                       'Event definition':st.column_config.SelectboxColumn(options=['','None','Message']),
                       'Event direction':st.column_config.SelectboxColumn(options=['','catch','throw']),
                       'Gateway type':st.column_config.SelectboxColumn(options=list(dict.fromkeys(['','Exclusive','Parallel','Inclusive']+[n.get('gateway_type','') for n in initial['nodes']])))},key='plan_nodes_'+key)
    decisions={r['Source ID']:{'action':r['Action'],'master_guid':r['Master GUID'],'ea_type':EA_LABEL_TYPES[r['Semantic Type']],
                              'business_id':r['Business ID'],'qualified_package_path':r['Qualified package path'],
                              'approved_new':r['Approve NEW'],'distinct_object_confirmed':r['Distinct object confirmed'],
                              'same_master_confirmed':r['Same master confirmed'],'event_definition':r['Event definition'],
                              'event_direction':r['Event direction'],'gateway_type':r['Gateway type']} for r in edited}
    current=build_plan(document,profile,snapshot,decisions)
    st.caption('REVIEW berarti NEEDS_REVIEW. Relasi adalah objek repository global. PROPOSE_CREATE belum mengizinkan penulisan. Konfirmasikan tipe/meaning serta persetujuan per baris.')
    relation_rows=[]
    nodes={n['id']:n for n in current['nodes']}
    for r in current['relationships']:
        relation_rows.append({'Source ID':r['id'],'Source':nodes[r['source']]['name'],'Source master GUID':r['source_guid'],
            'Target':nodes[r['target']]['name'],'Target master GUID':r['target_guid'],'Type':r['relationship_type'],
            'Name / meaning':r['name'],'Direction':r['direction'],'Existing ConnectorGUID':r['existing_connector_guid'],
            'Confirm semantics':r.get('semantic_confirmed',False),'Approve CREATE':False,'Accept existing properties':False,
            'Access type':'','Endpoint basis':r.get('endpoint_basis','explicit'),
            'Candidate ConnectorGUIDs':' | '.join(r.get('candidate_connector_guids',[])),'Action':r['action'],'Reason':r['reason']})
    if relation_rows:
        relation_edit=st.data_editor(relation_rows,hide_index=True,
            disabled=['Source ID','Source','Source master GUID','Target','Target master GUID','Endpoint basis','Candidate ConnectorGUIDs','Action','Reason'],
            column_config={'Type':st.column_config.SelectboxColumn(options=list(RELATION_TYPES),required=True),
                'Direction':st.column_config.SelectboxColumn(options=['Source -> Destination','Unspecified','Bi-Directional'],required=True),
                'Access type':st.column_config.SelectboxColumn(options=['','Read','Write','ReadWrite'])},key='plan_relations_'+key+hashlib.sha256(repr(decisions).encode()).hexdigest()[:8])
        for r in relation_edit:
            rbase[r['Source ID']]={'relationship_type':r['Type'],'name':r['Name / meaning'],'direction':r['Direction'],
                'existing_connector_guid':r['Existing ConnectorGUID'],'semantic_confirmed':r['Confirm semantics'],
                'approved_create':r['Approve CREATE'],'accept_existing_properties':r['Accept existing properties'],
                'tags':{'accessType':r['Access type']} if r['Access type'] else {}}
    plan=build_plan(document,profile,snapshot,decisions,rbase,mode=profile_context['execution'])
    st.write({'Elemen':plan['summary'],'Relasi':plan['relationship_summary'],'Mode':plan['mode']})
    if plan['errors']: st.warning(' | '.join(plan['errors']))
    with st.expander('Hasil preflight offline dan dry-run summary',expanded=True):
        st.dataframe([{'Source':n['name'],'Master GUID':n['master_guid'],'Package':(n.get('master') or {}).get('package_path',''),'Status':n['status'],'Reason':n['reason']} for n in plan['nodes']],hide_index=True)
        st.dataframe([{'Source ID':r['id'],'Source GUID':r['source_guid'],'Target GUID':r['target_guid'],'ConnectorGUID':r['existing_connector_guid'],
                       'Action':r['action'],'Reason':r['reason']} for r in plan['relationships']],hide_index=True)
    approved=False
    if plan['mode']=='EXECUTE':
        approved=st.checkbox('Saya menyetujui EXECUTE untuk rencana elemen dan relasi yang ditampilkan',
                             key='approve_'+plan['plan_digest'])
        if not plan['can_execute']: st.error('EXECUTE diblokir: selesaikan mapping, validasi, serta persetujuan setiap objek/relasi.')
    plan=build_plan(document,profile,snapshot,decisions,rbase,mode=profile_context['execution'],execute_approved=approved)
    st.download_button('Download dry-run plan (metadata JSON)',json.dumps(plan,ensure_ascii=False,indent=2),
                       file_name='diagramgene.import-plan.json',mime='application/json',key='download_plan_'+key)
    return plan,generate_jscript(plan)
