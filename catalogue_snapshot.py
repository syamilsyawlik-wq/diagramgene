"""Versioned, metadata-only snapshots. Legacy CSV remains a supported input."""
import json
import re
from ea_catalogue import guid, read_catalogue_csv
from model_types import EA_ELEMENT_TYPES
from repository_profiles import validate_identity


def semantic_type(base, stereotype):
    stereotypes = [s.strip() for s in stereotype.split(',') if s.strip()]
    return next((t for t in EA_ELEMENT_TYPES if '::' in t and t in stereotypes), base)


def read_snapshot(raw):
    text = raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw
    if not text.lstrip().startswith('{'):
        legacy = read_catalogue_csv(text)
        for element in legacy['elements']:
            element.update(base_type=element['ea_type'] if '::' not in element['ea_type'] else '',
                           package_guid=legacy['package_guid'], parent_guid='', alias='', business_id='', opco='', legacy=True)
        return {**legacy, 'schema_version':1, 'repository_identity':None, 'exported_at':'',
                'packages':[], 'connectors':[], 'metadata_complete':False}
    return normalise_snapshot(json.loads(text))


def normalise_snapshot(data, trusted_local=False):
    """Validate v2 dictionaries from JSON or a read-only repository provider."""
    if data.get('schema_version') != 2 or data.get('format') != 'diagramgene.catalogue':
        raise ValueError('Versi/schema snapshot katalog tidak didukung.')
    identity = validate_identity(data['repository_identity'])
    source=data.get('repository_source')
    if source is not None:
        if not isinstance(source,dict): raise ValueError('Provenance repository harus berupa object.')
        allowed={'provider','backend_path','fingerprint','signals','schema_fingerprint','captured_at','consistency',
                 'observed_markers','scope_guid','identity_confidence','identity_limitations'}
        source={key:value for key,value in source.items() if key in allowed}
        if source.get('provider')=='local_qea':
            if identity['kind']!='local' or not re.fullmatch('[0-9a-f]{64}',str(source.get('fingerprint',''))):
                raise ValueError('Identity/fingerprint provenance QEA tidak valid.')
            if not isinstance(source.get('backend_path'),str): raise ValueError('Provenance path QEA tidak valid.')
        # Uploaded JSON cannot authorize a server-side path read, even if it
        # contains a forged trusted_capture flag. Only in-process providers can.
        source['trusted_capture']=bool(trusted_local and source.get('provider')=='local_qea')
    if not isinstance(data.get('exported_at'),str) or not data['exported_at']:
        raise ValueError('Snapshot timestamp wajib diisi.')
    root = guid(data['package_guid'])
    packages, elements, connectors = data.get('packages'), data.get('elements'), data.get('connectors')
    if not all(isinstance(values,list) for values in (packages,elements,connectors)):
        raise ValueError('Snapshot harus memuat packages/elements/connectors sebagai array.')
    seen = set()
    for package in packages:
        package['guid'] = guid(package['guid'])
        package['parent_guid'] = guid(package['parent_guid']) if package.get('parent_guid') else ''
        if package['guid']==root and package['parent_guid']:
            raise ValueError('Root snapshot harus menjadi awal hierarchy katalog.')
        if package['guid'] in seen: raise ValueError('Package GUID duplikat dalam snapshot.')
        seen.add(package['guid'])
    if root not in seen: raise ValueError('Root katalog tidak terdapat dalam snapshot.')
    package_guids = set(seen)
    packages_by_guid={p['guid']:p for p in packages}
    for package in packages:
        if package['guid']!=root and package['parent_guid'] not in package_guids:
            raise ValueError('Hierarchy package snapshot terputus.')
        visited=set(); current=package
        while current.get('parent_guid'):
            if current['guid'] in visited: raise ValueError('Hierarchy package mengandung siklus.')
            visited.add(current['guid']); current=packages_by_guid[current['parent_guid']]
        if current['guid'] != root: raise ValueError('Package berada di luar root katalog.')
    seen=set()
    for element in elements:
        element['guid'] = guid(element['guid'])
        element['package_guid'] = guid(element['package_guid'])
        element['parent_guid'] = guid(element['parent_guid']) if element.get('parent_guid') else ''
        if element['guid'] in seen or element['package_guid'] not in package_guids:
            raise ValueError('Element GUID duplikat atau di luar scope katalog.')
        seen.add(element['guid'])
        if type(element.get('id')) is not int or element['id']<=0: raise ValueError('ElementID snapshot tidak valid.')
        for key in ('name','base_type','stereotype','alias','business_id','opco'):
            if not isinstance(element.get(key,''),str): raise ValueError('Metadata elemen harus berupa string.')
        element['ea_type']=semantic_type(element['base_type'],element['stereotype'])
        element.setdefault('package_path','');element.setdefault('tags',{})
        allowed_tags={'BusinessID','OPCO','DG_BusinessID','DG_OPCO','eventDefinition','gatewayType','activityType','isInterrupting','accessType'}
        if not isinstance(element['tags'],dict) or any(not isinstance(v,str) for v in element['tags'].values()):
            raise ValueError('Tagged metadata elemen tidak valid.')
        element['tags']={k:v for k,v in element['tags'].items() if k in allowed_tags}
        if not isinstance(element.get('bpmn_references',{}),dict): raise ValueError('Metadata reference BPMN tidak valid.')
        if element.get('element_tags_hash') and not re.fullmatch('[0-9a-f]{64}',str(element['element_tags_hash'])):
            raise ValueError('Hash tagged values BPMN tidak valid.')
    elements_by_guid={e['guid']:e for e in elements}
    for element in elements:
        if element['parent_guid'] and element['parent_guid'] not in seen: raise ValueError('Parent element tidak ada dalam scope snapshot.')
        visited=set();current=element
        while current.get('parent_guid'):
            if current['guid'] in visited: raise ValueError('Hierarchy element mengandung siklus.')
            visited.add(current['guid']);current=elements_by_guid[current['parent_guid']]
    relations=set()
    for connector in connectors:
        connector['guid']=guid(connector['guid'])
        connector['source_guid']=guid(connector['source_guid']);connector['target_guid']=guid(connector['target_guid'])
        if connector['guid'] in relations: raise ValueError('Connector GUID duplikat.')
        relations.add(connector['guid'])
        if connector['source_guid'] not in seen or connector['target_guid'] not in seen:
            connector['metadata_complete']=False
        if connector.get('metadata_complete'):
            if type(connector.get('id')) is not int or connector['id']<=0: raise ValueError('ConnectorID snapshot tidak valid.')
            fields=('base_type','stereotype','name','direction','tags_hash','notes_hash')
            if any(not isinstance(connector.get(k),str) for k in fields):
                raise ValueError('Metadata connector tidak lengkap.')
            if not re.fullmatch('[0-9a-f]{64}',connector['tags_hash']): raise ValueError('Hash tagged values connector tidak valid.')
            if not re.fullmatch('[0-9a-f]{64}',connector['notes_hash']): raise ValueError('Hash Notes connector tidak valid.')
            role_keys={'Role','Cardinality','Aggregation','Navigable','RoleType','Alias','Qualifier','Containment','Visibility','Derived','Ordering','role_note_hash'}
            for key in ('source_role','target_role'):
                role=connector.get(key)
                if not isinstance(role,dict) or set(role)!=role_keys:
                    connector['metadata_complete']=False
                elif any(not isinstance(v,(str,int,bool)) for v in role.values()):
                    raise ValueError('Metadata role connector tidak valid.')
    # Whitelist the metadata contract. Uploaded notes/credentials/arbitrary fields
    # must not be copied into generated plans even if a hand-edited JSON adds them.
    def select(record, keys): return {key:record[key] for key in keys if key in record}
    return {'format':data['format'],'schema_version':2,'repository_identity':identity,
            'exported_at':data['exported_at'],'package_guid':root,'metadata_complete':True,'repository_source':source,
            'skipped':sum(e['ea_type'] not in EA_ELEMENT_TYPES for e in elements),
            'packages':[select(p,('guid','id','parent_guid','name','path')) for p in packages],
            'elements':[select(e,('guid','id','name','alias','base_type','stereotype','ea_type','package_guid','parent_guid','package_path','business_id','opco','tags','bpmn_references','element_tags_hash','metadata_status','metadata_reasons','uninterpreted_xrefs')) for e in elements],
            'connectors':[select(c,('guid','id','source_guid','target_guid','base_type','stereotype','name','direction','source_role','target_role','tags_hash','notes_hash','semantic_tags','metadata_complete','reason','metadata_status','metadata_reasons','uninterpreted_xrefs')) for c in connectors]}
