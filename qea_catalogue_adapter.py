"""EA SQLite records -> the existing v2 catalogue, with explicit uncertainty.

Storage mappings here are a supported subset, not a claim of EA-version parity.
Missing/unknown semantic metadata blocks reuse; no API property is fabricated.
"""
from collections import defaultdict
import hashlib
import re

from catalogue_snapshot import normalise_snapshot
from ea_catalogue import guid
from import_plan import canonical, fingerprint
from model_types import EA_ELEMENT_TYPES, RELATION_TYPES

SAFE_TAGS={'BusinessID','DG_BusinessID','OPCO','DG_OPCO','eventDefinition',
           'gatewayType','activityType','isInterrupting','accessType'}
REFERENCES={'processref','participantref','partitionelement','partitionelementref','partnerentity','partnerrole','calledactivity'}
KNOWN_QUALIFIED=set(EA_ELEMENT_TYPES)|{stereo for _base,stereo in RELATION_TYPES.values() if stereo}


def text(value): return '' if value is None else str(value)
def digest(value): return hashlib.sha256(text(value).encode('utf-8')).hexdigest()


def wine_locator(path):
    """A *proposal* for Wine's default Z: mapping, never a verified identity."""
    path=str(path).replace('\\','/')
    return path if re.match(r'^[A-Za-z]:/',path) else 'Z:'+path


def stereotypes(row,xrefs):
    raw=text(row.get('stereotype'));values=[v.strip() for v in raw.split(',') if v.strip()]
    qualified=[];unknown=[];issues=[]
    for record in xrefs:
        if text(record.get('name')).lower()=='stereotypes':
            description=text(record.get('description'))
            found=re.findall(r'(?:^|;)FQName=([^;]+);',description)
            if not found and description: issues.append('Format FQName t_xref belum didukung.')
            qualified.extend(found)
        else:
            unknown.append({'name':text(record.get('name')),'hash':digest(record.get('description'))})
    result=[]
    for value in values:
        matches=[q for q in qualified if q==value or q.rsplit('::',1)[-1]==value]
        if '::' in value: matches=[value] if not matches else matches
        if len(set(matches))==1: result.extend(matches)
        else: issues.append('Stereotype tidak qualified/ambigu: '+value)
    for value in qualified:
        if value not in result: result.append(value)
    if any(value not in KNOWN_QUALIFIED for value in result):
        issues.append('MDG/stereotype belum didukung.')
    # Raw names are preserved when qualification is unknown; never guess a MDG.
    if not result and values: result=values
    if unknown: issues.append('Ada t_xref tambahan yang semantiknya belum diverifikasi.')
    return ','.join(sorted(set(result))),issues,unknown


def tagged(records,notes_available=True):
    entries=[];safe={};references={};issues=[];seen=set()
    for row in records:
        name=text(row.get('property'));value=text(row.get('value'))
        if name in seen: issues.append('Nama tagged value duplikat: '+name)
        seen.add(name)
        entry=[name,value]
        if value=='<memo>':
            if not notes_available: issues.append('Body memo tagged value tidak tersedia.')
            entry.append(digest(row.get('notes')))
        entries.append(entry)
        if name in SAFE_TAGS and value!='<memo>': safe[name]=value
        elif name in SAFE_TAGS: issues.append('Tag semantik memo perlu interpretasi native: '+name)
        reference=re.sub('[^a-z]','',name.lower())
        if reference in REFERENCES and value and value.lower() not in ('0','none','<none>'):
            references[name]=value
    entries.sort(key=lambda item:canonical(item).encode('utf-16-be'))
    return fingerprint(entries),safe,references,issues


def role(row,prefix):
    p=prefix.lower();result={};issues=[]
    mapping={'Role':'role','Cardinality':'card','RoleType':'roletype','Qualifier':'qualifier'}
    for target,source in mapping.items():
        if p+source not in row: issues.append('Kolom role tidak tersedia: '+p+source)
        else: result[target]=text(row[p+source])
    for target,source in [('Aggregation','isaggregate'),('Ordering','isordered')]:
        value=row.get(p+source)
        try:
            if str(value).lower() in ('true','false'): value=int(str(value).lower()=='true')
            number=int(value)
            if number not in (0,1,2): raise ValueError()
            result[target]=number
        except (TypeError,ValueError): issues.append('Nilai role numerik belum didukung: '+p+source)
    value=row.get(p+'isderived')
    if text(value).lower() in ('0','false','1','true'): result['Derived']=text(value).lower() in ('1','true')
    else: issues.append('Derived role tidak tersedia/tidak dikenal.')
    navigable={'true':'Navigable','1':'Navigable','false':'Non-Navigable','0':'Non-Navigable',
               'navigable':'Navigable','non-navigable':'Non-Navigable','unspecified':'Unspecified'}
    if text(row.get(p+'isnavigable')).lower() in navigable:
        result['Navigable']=navigable[text(row[p+'isnavigable']).lower()]
    else: issues.append('Navigability role belum dapat dipastikan.')
    for target,source,allowed in [('Visibility','access',('Public','Private','Protected','Package')),
                                 ('Containment','containment',('Unspecified','Value','Reference'))]:
        value=text(row.get(p+source));normalized=value.title()
        if p+source not in row or normalized not in allowed: issues.append(target+' role belum didukung.')
        else: result[target]=normalized
    if p+'alias' in row: result['Alias']=text(row[p+'alias'])
    elif p+'style' in row:
        style=text(row[p+'style']);parts=[s for s in style.split(';') if s]
        if not parts: result['Alias']=''
        elif all(s.lower().startswith('alias=') for s in parts) and len(parts)==1: result['Alias']=parts[0].split('=',1)[1]
        else: issues.append('Style end connector mempunyai metadata yang belum didukung.')
    else: issues.append('Alias/style end connector tidak tersedia.')
    if p+'rolenote' not in row: issues.append('RoleNote fingerprint tidak tersedia.')
    else: result['role_note_hash']=digest(row[p+'rolenote'])
    if p+'alias' in row and text(row.get(p+'style')):
        parts=[s for s in text(row[p+'style']).split(';') if s]
        if any(s!='alias='+result['Alias'] for s in parts):
            issues.append('Style end connector mempunyai metadata tambahan yang belum didukung.')
    # Do not merge away ownership/constraints hidden outside the v2 end contract.
    for field in ('constraint','isowned','isduplicate','ischangeable'):
        if text(row.get(p+field)).lower() not in ('','0','false'):
            issues.append('Properti end tambahan memerlukan validasi native: '+p+field)
    return result,issues


def adapt(raw):
    overview=raw['overview'];root_id=raw['root_id'];packages_by_id={p['package_id']:p for p in raw['packages']}
    if packages_by_id[root_id]['parent_id'] in packages_by_id:
        raise ValueError('Hierarchy package mengandung siklus pada root scope.')
    elements_by_id={e['object_id']:e for e in raw['elements']}
    endpoint_guids={r['object_id']:guid(r['ea_guid']) for r in raw['endpoints']}
    endpoint_guids.update({key:guid(row['ea_guid']) for key,row in elements_by_id.items()})
    tags_by_id=defaultdict(list);connector_tags=defaultdict(list);xrefs=defaultdict(list)
    for tag in raw['object_tags']: tags_by_id[tag['object_id']].append(tag)
    for tag in raw['connector_tags']: connector_tags[tag[raw['connector_tag_key'].lower()]].append(tag)
    for row in raw['xrefs']: xrefs[guid(row['client'])].append(row)
    paths={}
    def path(key,seen=None):
        if key in paths: return paths[key]
        seen=set() if seen is None else seen
        if key in seen: raise ValueError('Hierarchy package mengandung siklus.')
        seen.add(key);p=packages_by_id[key]
        value=text(p['name']) if key==root_id else path(p['parent_id'],seen)+' / '+text(p['name'])
        paths[key]=value;return value
    packages=[{'guid':guid(p['ea_guid']),'id':p['package_id'],'name':text(p['name']),
               'parent_guid':'' if p['package_id']==root_id else guid(packages_by_id[p['parent_id']]['ea_guid']),
               'path':path(p['package_id'])} for p in raw['packages']]
    elements=[];connectors=[]
    for row in raw['elements']:
        key=guid(row['ea_guid']);stereo,issues,unknown=stereotypes(row,xrefs[key])
        tag_hash,tags,references,tag_issues=tagged(tags_by_id[row['object_id']], 'notes' in raw['schema']['t_objectproperties'])
        issues+=tag_issues
        if stereo and row['object_type'] in ('Note','Boundary'):
            issues.append('Base type visual tidak dapat dipakai sebagai master berstereotype semantik.')
        for field in ('classifier','classifier_guid','ntype','pdata1','pdata2','pdata3','pdata4','pdata5','stateflags'):
            if text(row.get(field)) not in ('','0'): issues.append('Metadata elemen tambahan perlu review: '+field)
        parent=row['parentid'] or 0
        if parent and parent not in elements_by_id:
            raise ValueError('Lingkup memotong parent elemen. Pilih package induk yang mencakup seluruh owning Pool/Lane/process.')
        elements.append({'guid':key,'id':row['object_id'],'name':text(row['name']),'alias':text(row.get('alias')),
            'base_type':row['object_type'],'stereotype':stereo,'package_guid':guid(packages_by_id[row['package_id']]['ea_guid']),
            'parent_guid':guid(elements_by_id[parent]['ea_guid']) if parent else '', 'package_path':path(row['package_id']),
            'business_id':tags.get('DG_BusinessID') or tags.get('BusinessID',''),'opco':tags.get('DG_OPCO') or tags.get('OPCO',''),
            'tags':tags,'bpmn_references':references,'element_tags_hash':tag_hash if not tag_issues else '',
            'metadata_status':'NEEDS_REVIEW' if issues else 'RESOLVED','metadata_reasons':issues,'uninterpreted_xrefs':unknown})
    for row in raw['connectors']:
        key=guid(row['ea_guid']);stereo,issues,unknown=stereotypes(row,xrefs[key])
        source,target=row['start_object_id'],row['end_object_id']
        if source not in endpoint_guids or target not in endpoint_guids:
            raise ValueError('Connector menunjuk ke endpoint yang tidak ditemukan dalam database.')
        source_role,source_issues=role(row,'Source');target_role,target_issues=role(row,'Dest')
        tag_hash,tags,_refs,tag_issues=tagged(connector_tags[row['connector_id']], 'notes' in raw['schema'].get('t_connectortag',{}))
        issues+=source_issues+target_issues+tag_issues
        if not raw['connector_tag_key']: issues.append('Tabel tagged values connector tidak tersedia/kolom tidak dikenal.')
        for field in ('name','direction','notes'):
            if field not in row: issues.append('Metadata connector tidak tersedia: '+field)
        for field in ('subtype','pdata1','pdata2','pdata3','pdata4','pdata5','styleex','stateflags'):
            if text(row.get(field)) not in ('','0'): issues.append('Metadata connector tambahan perlu review: '+field)
        if source not in elements_by_id or target not in elements_by_id: issues.append('Endpoint berada di luar lingkup katalog.')
        connectors.append({'guid':key,'id':row['connector_id'],'name':text(row.get('name')),
            'source_guid':endpoint_guids[source],'target_guid':endpoint_guids[target],
            'base_type':row['connector_type'],'stereotype':stereo,'direction':text(row.get('direction')),
            'source_role':source_role,'target_role':target_role,'tags_hash':tag_hash,'notes_hash':digest(row.get('notes')),
            'semantic_tags':{'accessType':tags['accessType']} if 'accessType' in tags else {},
            'metadata_complete':not issues,'metadata_status':'NEEDS_REVIEW' if issues else 'RESOLVED',
            'metadata_reasons':issues,'uninterpreted_xrefs':unknown})
    source={'provider':'local_qea','backend_path':overview['path'],'fingerprint':overview['fingerprint'],
            'signals':overview['signals'],'schema_fingerprint':overview['schema_fingerprint'],
            'captured_at':overview['captured_at'],'consistency':overview['consistency'],
            'observed_markers':overview['observed_markers'],'scope_guid':guid(packages_by_id[root_id]['ea_guid']),
            'identity_confidence':'locator_and_model_metadata_not_globally_unique',
            'identity_limitations':'Wine locator is proposed; clones can retain GUIDs. Runtime must check actual locator and selected model IDs/types/relationships. File provenance is rechecked before generation, not readable through EA Automation API.'}
    return normalise_snapshot({'format':'diagramgene.catalogue','schema_version':2,
        'repository_identity':{'kind':'local','locator':wine_locator(overview['path'])},
        'exported_at':overview['captured_at'],'package_guid':source['scope_guid'],
        'packages':packages,'elements':elements,'connectors':connectors,'repository_source':source},trusted_local=True)
