"""Local-path repository discovery and bounded, read-only Streamlit inspection."""
import json
from pathlib import Path

import streamlit as st

from catalogue_snapshot import read_snapshot
from qea_catalogue_adapter import wine_locator
from qea_reader import QEAError, local_access_policy, probe
from repository_profiles import load_profiles, normalise_profile, save_profiles
from repository_providers import LocalQEARepositoryProvider


def package_picker(provider,label,key):
    search=st.text_input('Cari nama package — '+label,key='search_'+key)
    page=st.number_input('Halaman package — '+label,min_value=1,step=1,key='page_'+key)
    packages=provider.packages(search=search,offset=(int(page)-1)*50,limit=50)
    choices={p['package_id']:p for p in packages}
    selected=st.selectbox(label,list(choices),index=None,
        format_func=lambda value:choices[value]['path']+' · '+choices[value]['ea_guid'],key=key)
    st.caption('Maksimal 50 package per halaman. Pencarian mencakup seluruh hierarchy.')
    return choices.get(selected)


def inspector(provider,scope,key):
    if not st.checkbox('Buka inspector read-only',key='inspect_'+key): return
    sections={'Hierarchy package':'packages','Elemen':'elements','Diagram':'diagrams',
              'Relasi':'relationships','Stereotype / tipe elemen':'types','Objek pada diagram':'objects'}
    section=sections[st.selectbox('Bagian inspector',list(sections),key='section_'+key)]
    search=st.text_input('Filter nama',key='inspect_name_'+key) if section!='types' else ''
    ea_type=st.text_input('Filter tipe elemen / connector / diagram',key='inspect_type_'+key) if section!='packages' else ''
    stereo=st.text_input('Filter stereotype',key='inspect_stereo_'+key) if section not in ('packages','diagrams') else ''
    guid_filter=st.text_input('Filter GUID',key='inspect_guid_'+key) if section!='types' else ''
    page=int(st.number_input('Halaman inspector (50 baris)',min_value=1,step=1,key='inspect_page_'+key))
    if section=='packages':
        rows=provider.packages(search=search,guid_filter=guid_filter,offset=(page-1)*50,limit=50)
        st.caption('Hierarchy package: seluruh repository. Bagian lain dibatasi package katalog beserta turunannya.')
    else:
        rows=provider.page(section,scope['package_id'],search=search,ea_type=ea_type,stereotype=stereo,
                           guid_filter=guid_filter,offset=(page-1)*50,limit=50)
    st.dataframe(rows,hide_index=True)


def local_controls(saved,name):
    snapshot=None;derived={};force=False
    st.caption('Path file berada pada mesin backend DiagramGene, bukan mesin browser. Tutup penulisan EA sebelum analisis. Tidak ada upload/copy file database.')
    try: allowed_root=local_access_policy(st.get_option('server.address'))
    except QEAError as exc:
        st.error(str(exc));return snapshot,derived
    path=st.text_input('Path file .qea lokal',placeholder='/Users/nama/EA/testing.qea',key='qea_path_'+name)
    analyze=st.button('Analisis repository',key='qea_analyze_'+name)
    force=st.button('Segarkan repository',key='qea_refresh_'+name)
    if not path:
        st.info('Masukkan path .qea untuk membaca metadata secara read-only.')
        return snapshot,derived
    state_key='qea_capture_'+name
    try:
        source=probe(path,allowed_root)
        st.caption('File ditemukan · '+source['path'])
        if analyze or force:
            overview=LocalQEARepositoryProvider(path,allowed_root).overview()
            st.session_state[state_key]={'overview':overview,'force_cache':bool(force)}
        captured=st.session_state.get(state_key)
        if not captured or captured['overview']['fingerprint']!=source['fingerprint']:
            st.warning('Belum dianalisis atau file berubah. Tekan Analisis / Segarkan repository; mapping lama tidak digunakan.')
            return snapshot,derived
        overview=captured['overview'];key=name+'_'+source['fingerprint'][:16]+'_'+overview['captured_at']
        provider=LocalQEARepositoryProvider(path,allowed_root,expected_fingerprint=source['fingerprint'])
        st.write(overview['name'])
        st.caption(f"Ukuran {source['signals']['size']/1048576:.2f} MiB · dianalisis {overview['captured_at']}")
        st.write({'Package':overview['counts']['t_package'],'Elemen':overview['counts']['t_object'],
                  'Diagram':overview['counts']['t_diagram'],'Connector':overview['counts']['t_connector'],
                  'Stereotype tersimpan (belum qualified)':overview['stereotype_count']})
        scope=package_picker(provider,'Package katalog / scope','qea_scope_'+key)
        output=package_picker(provider,'Package output diagram','qea_output_'+key)
        if scope:
            # Keep only one derived scope in session; disk cache is bounded too.
            if force or captured.get('scope')!=scope['package_id'] or not captured.get('snapshot'):
                captured['snapshot']=provider.catalogue(scope['package_id'],force=captured.pop('force_cache',False))
                captured['scope']=scope['package_id']
                captured['cache_hit']=provider.last_cache_hit
            snapshot=captured['snapshot']
            st.caption(f"Katalog scope: {len(snapshot['elements'])} elemen, {len(snapshot['connectors'])} relasi · "+
                       ('cache metadata' if captured.get('cache_hit') else 'capture read-only'))
            uncertain=sum(e.get('metadata_status')=='NEEDS_REVIEW' for e in snapshot['elements'])
            incomplete=sum(not c.get('metadata_complete') for c in snapshot['connectors'])
            if uncertain or incomplete:
                st.warning(f'{uncertain} elemen dan {incomplete} relasi membutuhkan review metadata. Reuse diblokir untuk metadata yang belum didukung; exporter JSON tetap tersedia.')
            inspector(provider,scope,key)
        with st.expander('Pengaturan lanjutan — identitas Wine'):
            locator=st.text_input('Path repository seperti terlihat oleh EA/Wine',value=wine_locator(source['path']),key='wine_'+key)
            st.caption('Z: adalah usulan pemetaan default Wine. Bandingkan dengan repository aktif di EA. Path dan GUID bukan identitas global; clone dapat mempertahankan GUID yang sama. JScript tetap memeriksa locator, ID, tipe, scope, parent, dan relasi aktual.')
            reviewed=st.checkbox('Saya sudah memeriksa pemetaan path Wine untuk capture ini',key='wine_review_'+key)
            st.json({'schema_fingerprint':overview['schema_fingerprint'],'fingerprint':source['fingerprint'],
                     'observed_markers':overview['observed_markers'],'consistency':overview['consistency']})
        derived={'expected_identity':{'kind':'local','locator':locator},'qea_identity_reviewed':reviewed,
                 'catalogue_root_guid':scope['ea_guid'] if scope else '',
                 'scope_package_guid':scope['ea_guid'] if scope else '',
                 'output_package_guid':output['ea_guid'] if output else '',
                 'last_snapshot_at':overview['captured_at']}
        if snapshot:
            # Session catalogue is immutable; a locator adjustment affects only this context.
            snapshot={**snapshot,'repository_identity':derived['expected_identity']}
        if saved['environment']=='production':
            st.error('File QEA lokal hanya untuk Local Testing. Gunakan snapshot repository server berotorisasi untuk Holding Production.')
            snapshot=None;derived['expected_identity']=None;derived['qea_identity_reviewed']=False
    except (QEAError,OSError,ValueError) as exc:
        st.error(str(exc));snapshot=None;derived={'expected_identity':None,'qea_identity_reviewed':False}
    return snapshot,derived


def snapshot_controls(saved,name):
    metadata=st.file_uploader('Snapshot repository EA (JSON v2 / CSV legacy)',type=['json','csv'],key='repository_snapshot')
    st.download_button('Exporter snapshot v2 (read-only)',Path(__file__).with_name('export_ea_catalogue.js').read_text(),file_name='export_ea_catalogue.js')
    snapshot=None
    if metadata:
        try: snapshot=read_snapshot(metadata.getvalue())
        except (ValueError,KeyError,TypeError,UnicodeError) as exc: st.error(str(exc))
    with st.expander('Pengaturan lanjutan — snapshot'):
        identity=st.text_area('Expected repository identity (non-secret JSON)',
            value=json.dumps(saved.get('expected_identity') or (snapshot or {}).get('repository_identity') or {},ensure_ascii=False),key='identity_'+name+'_'+str(bool(snapshot)))
        root=st.text_input('Catalogue root GUID (profile)',value=saved.get('catalogue_root_guid') or (snapshot or {}).get('package_guid',''),key='root_'+name+'_'+str(bool(snapshot)))
        scope=st.text_input('Scope package GUID / OPCO catalogue',value=saved.get('scope_package_guid',''),key='scope_'+name)
        output=st.text_input('Output package GUID (production: wajib)',value=saved.get('output_package_guid',''),key='output_'+name)
    try: parsed=json.loads(identity) or None
    except (ValueError,TypeError): parsed=None;st.error('Expected repository identity harus berupa JSON non-rahasia yang valid.')
    return snapshot,{'expected_identity':parsed,'catalogue_root_guid':root,'scope_package_guid':scope,
                     'output_package_guid':output,'qea_identity_reviewed':False,
                     'last_snapshot_at':(snapshot or {}).get('exported_at',saved.get('last_snapshot_at',''))}


def repository_controls():
    try: profiles=load_profiles()
    except (ValueError,OSError) as exc:
        st.sidebar.error(str(exc));profiles={name:normalise_profile({'name':name,'environment':env}) for name,env in [('Local Testing','local'),('Holding Production','production')]}
    with st.sidebar.expander('Repository EA',expanded=True):
        name=st.selectbox('Repository profile',list(profiles),key='repository_profile');saved=profiles[name]
        source=st.selectbox('Sumber repository',['File QEA lokal','Snapshot JSON/CSV (lanjutan)'],key='repository_source')
        snapshot,derived=local_controls(saved,name) if source=='File QEA lokal' else snapshot_controls(saved,name)
        with st.expander('Kebijakan impor lanjutan'):
            opco=st.text_input('OPCO / namespace impor',value=saved.get('opco',''),key='opco_'+name)
            allow_new=st.checkbox('Izinkan elemen lokal baru (tetap perlu persetujuan per elemen)',value=saved['allow_new_elements'],key='new_'+name)
        execution=st.radio('Mode runtime JScript',['VALIDATE_ONLY','EXECUTE'],key='exec_'+name)
        profile={**saved,**derived,'opco':opco,'allow_new_elements':allow_new}
        # No previously saved path review can authorize a new capture.
        if source=='File QEA lokal' and not derived: profile.update(expected_identity=None,qea_identity_reviewed=False,catalogue_root_guid='',scope_package_guid='',output_package_guid='')
        try: profile=normalise_profile(profile)
        except (ValueError,TypeError) as exc:
            st.error(str(exc));profile={**saved,'expected_identity':None,'qea_identity_reviewed':False}
        st.caption('Default VALIDATE_ONLY. Memilih profil tidak mengubah repository aktif di EA dan tidak memberi izin produksi.')
        if st.button('Simpan metadata profile lokal'):
            profiles[name]=profile
            try: save_profiles(profiles);st.success('Profile non-rahasia tersimpan lokal; diabaikan Git.')
            except (ValueError,OSError) as exc: st.error(str(exc))
    return {'profile':profile,'snapshot':snapshot,'execution':execution,
            'provider':'local_qea' if source=='File QEA lokal' else 'json_snapshot'}
