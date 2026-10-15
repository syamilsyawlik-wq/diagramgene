"""Conservative, explicitly supported relationship rules; unsupported cases fail closed."""
BPMN_PREFIX = 'BPMN2.0::'
BPMN_TYPES = {kind: BPMN_PREFIX + name for kind, name in {
    'pool': 'Pool', 'lane': 'Lane', 'task': 'Activity', 'subprocess': 'Activity',
    'gateway': 'Gateway', 'start': 'StartEvent', 'end': 'EndEvent',
    'link': 'IntermediateEvent', 'data': 'DataObject', 'annotation':'TextAnnotation'}.items()}
BPMN_RELATIONS = {
    'BPMN: Sequence Flow': ('ControlFlow', BPMN_PREFIX+'SequenceFlow'),
    'BPMN: Message Flow': ('ControlFlow', BPMN_PREFIX+'MessageFlow'),
    'BPMN: Data Association': ('Dependency', BPMN_PREFIX+'DataAssociation'),
    'BPMN: Association': ('Association', BPMN_PREFIX+'Association'),
}
ARCH_RULES = {
    'Assignment': [('BusinessActor','BusinessRole'),('BusinessActor','BusinessProcess'),('BusinessRole','BusinessProcess'),
                   ('ApplicationComponent','ApplicationFunction'),('Node','TechnologyService'),('SystemSoftware','TechnologyService')],
    'Serving': [('BusinessService',t) for t in ('BusinessActor','BusinessRole','BusinessProcess')] +
               [('ApplicationService',t) for t in ('BusinessProcess','BusinessRole','ApplicationComponent')] +
               [('TechnologyService',t) for t in ('ApplicationComponent','Node','SystemSoftware')],
    'Realization': [('BusinessProcess','BusinessService'),('ApplicationFunction','ApplicationService'),
                    ('Artifact','ApplicationComponent'),('Artifact','DataObject')],
}
ACCESS_SOURCES = ['BusinessActor','BusinessRole','BusinessProcess','BusinessService','ApplicationComponent',
                  'ApplicationFunction','ApplicationService','Node','Device','SystemSoftware','TechnologyService']
PASSIVE = ['BusinessObject','DataObject','Artifact']
FLOW_GROUPS = [['BusinessActor','BusinessRole','BusinessProcess','BusinessService'],
               ['ApplicationComponent','ApplicationFunction','ApplicationService'],
               ['Node','Device','SystemSoftware','TechnologyService']]
TRIGGER_GROUPS = [['BusinessProcess','BusinessService'],['ApplicationFunction','ApplicationService'],['TechnologyService']]


def node_error(node):
    """Fail closed for BPMN features outside the verified metadata contract."""
    if not node['ea_type'].startswith(BPMN_PREFIX): return None
    kind=node['kind']; tags=(node.get('master') or {}).get('tags',{})
    if any(tags.get(key)=='<memo>' for key in ('eventDefinition','gatewayType','activityType','isInterrupting')):
        return 'Semantic property BPMN berupa memo belum didukung; perlu review native di EA.'
    if node['status']=='REUSE' and not node['master'].get('element_tags_hash'):
        return 'Metadata tagged values BPMN tidak lengkap; ekspor ulang atau tangani manual di EA.'
    if node['status']=='REUSE' and node['master'].get('bpmn_references'):
        return 'Master mempunyai semantic reference BPMN yang belum dapat diverifikasi; perlu mapping manual di EA (P1).'
    required='activityType' if kind in ('task','subprocess') else 'gatewayType' if kind=='gateway' else 'eventDefinition' if kind in ('start','end','link') else None
    if node['status']=='REUSE' and required and required not in tags:
        return 'Native semantic property BPMN master tidak tersedia: '+required
    if 'boundary' in node.get('original_shape','').lower():
        return 'Boundary Event/attachment belum didukung; perlu pemodelan manual di EA.'
    if kind=='subprocess' and node['status']=='REUSE' and tags.get('activityType')!='Sub-Process':
        return 'Activity master bukan Sub-Process yang terverifikasi.'
    if kind=='task' and tags.get('activityType') not in (None,'','Task'):
        return 'Activity master mempunyai activityType berbeda; jangan reuse sebagai Task.'
    if kind=='gateway' and node.get('gateway_type',tags.get('gatewayType','Exclusive')) not in ('Exclusive','Parallel','Inclusive'):
        return 'Complex/Event-based Gateway belum didukung oleh validator subset ini.'
    if kind=='gateway' and node['status']=='REUSE' and node.get('gateway_type',tags['gatewayType'])!=tags['gatewayType']:
        return 'Gateway type sumber berbeda dari master BPMN.'
    if kind in ('start','end','link'):
        expected=node.get('event_definition','None')
        if expected not in ('None','Message'): return 'Event definition belum didukung.'
        if node['status']=='REUSE' and tags.get('eventDefinition','None')!=expected:
            return 'Event definition sumber berbeda dari master BPMN.'
    return None


def relation_error(source, target, relation):
    """None means valid in our supported subset, not complete metamodel certification."""
    kind = relation['relationship_type']
    st, tt = source['ea_type'], target['ea_type']
    if relation.get('direction') not in ('Source -> Destination','Unspecified','Bi-Directional'):
        return 'Direction tidak didukung.'
    if kind.startswith('BPMN:'):
        sk, tk = source['kind'], target['kind']
        if any(n['ea_type']!=BPMN_TYPES.get(n['kind']) for n in (source,target)):
            return 'Endpoint BPMN memerlukan semantic type BPMN yang sesuai, bukan hanya bentuk visual.'
        flow = {'task','subprocess','gateway','start','end','link'}
        same_pool = bool(source.get('pool')) and source.get('pool') == target.get('pool')
        same_scope = source.get('process_scope') == target.get('process_scope')
        if kind == 'BPMN: Sequence Flow':
            if sk not in flow or tk not in flow: return 'Sequence Flow hanya menghubungkan flow node BPMN.'
            if not same_pool: return 'Sequence Flow lintas Pool dilarang.'
            if not same_scope: return 'Sequence Flow lintas scope subprocess dilarang.'
            if sk == 'end' or tk == 'start': return 'End Event tidak boleh outgoing / Start Event tidak boleh incoming Sequence Flow.'
        elif kind == 'BPMN: Message Flow':
            if same_pool or not source.get('pool') or not target.get('pool'): return 'Message Flow harus menghubungkan participant/Pool berbeda.'
            if sk not in {'pool','task','subprocess','start','end','link'} or tk not in {'pool','task','subprocess','start','end','link'}:
                return 'Message Flow tidak boleh memakai Lane/Gateway/Data Object sebagai endpoint.'
            for node, is_source in ((source,True),(target,False)):
                if node['kind'] in {'start','end','link'}:
                    if node.get('event_definition') != 'Message': return 'Message Flow pada Event memerlukan Message event definition terverifikasi.'
                    if is_source and (node['kind']=='start' or node.get('event_direction')!='throw'): return 'Sumber Message Flow harus throwing Event.'
                    if not is_source and (node['kind']=='end' or node.get('event_direction')!='catch'): return 'Target Message Flow harus catching Event.'
        elif kind == 'BPMN: Data Association':
            if not same_pool or not same_scope: return 'Data Association harus tetap dalam scope proses yang didukung.'
            if not ((sk=='data' and tk in {'task','subprocess'}) or (tk=='data' and sk in {'task','subprocess'})):
                return 'Data Association yang didukung menghubungkan Data Object dan Activity.'
        elif kind == 'BPMN: Association':
            if not same_pool or not same_scope: return 'Association artefak lintas scope proses belum didukung.'
            if not ((sk=='annotation' and tk in flow|{'data'}) or (tk=='annotation' and sk in flow|{'data'})):
                return 'Association BPMN yang didukung menghubungkan Text Annotation ke flow node/Data Object.'
        else: return 'Tipe connector BPMN tidak didukung.'
        if kind != 'BPMN: Association' and relation['direction'] != 'Source -> Destination':
            return 'Connector BPMN ini memerlukan arah source ke target.'
        return None
    if kind.startswith('ArchiMate:'):
        if not st.startswith('ArchiMate3::ArchiMate_') or not tt.startswith('ArchiMate3::ArchiMate_'):
            return 'Kedua endpoint harus mempunyai tipe ArchiMate yang terverifikasi.'
        s, t = st.split('ArchiMate_',1)[1], tt.split('ArchiMate_',1)[1]
        rel = kind.split(': ',1)[1]
        if rel == 'Association': return None
        if relation['direction'] != 'Source -> Destination': return 'Relasi ArchiMate terarah tidak boleh dibalik atau dua arah.'
        if rel in ARCH_RULES:
            if (s,t) not in ARCH_RULES[rel]: return 'Pasangan tipe tidak diizinkan oleh subset metamodel ArchiMate yang didukung.'
        elif rel == 'Access':
            if s not in ACCESS_SOURCES or t not in PASSIVE: return 'Access memerlukan active/behavior element ke passive structure.'
            if not any(s in group and t==passive for group,passive in zip(FLOW_GROUPS,PASSIVE)):
                return 'Access lintas lapisan berada di luar subset yang didukung.'
            if relation.get('tags',{}).get('accessType') not in ('Read','Write','ReadWrite'):
                return 'Access memerlukan accessType Read, Write, atau ReadWrite yang dikonfirmasi.'
        elif rel in ('Flow','Triggering'):
            groups = FLOW_GROUPS if rel=='Flow' else TRIGGER_GROUPS
            if not any(s in group and t in group for group in groups): return 'Pasangan Flow/Triggering di luar subset/lapisan yang didukung.'
        else: return 'Tipe ArchiMate belum didukung.'
        return None
    if kind not in ('Association','Dependency','Realisation','Generalization'):
        return 'Tipe relasi belum didukung.'
    if st.startswith(BPMN_PREFIX) or tt.startswith(BPMN_PREFIX):
        return 'Endpoint BPMN harus memakai tipe relasi BPMN yang eksplisit.'
    if 'ArchiMate3::' in st or 'ArchiMate3::' in tt:
        return 'Gunakan qualified ArchiMate relationship untuk endpoint ArchiMate.'
    if kind == 'Generalization' and st != tt: return 'Generalization lintas tipe belum didukung.'
    if kind in ('Dependency','Realisation','Generalization') and relation['direction']!='Source -> Destination':
        return 'Relasi UML ini memerlukan arah source ke destination yang eksplisit.'
    if kind == 'Realisation' and (st,tt) not in [('Class','Interface'),('Component','Interface')]:
        return 'Realisation hanya didukung untuk Class/Component ke Interface.'
    return None
