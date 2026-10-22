"""Bounded, read-only access to local EA SQLite repositories.

No model writes, copies, extensions, attach, or migrations. Database handles live
only for one read transaction. WAL/hot-journal repositories are deliberately not
supported yet; a consistent Backup API provider is a separate milestone.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time

TABLES = frozenset(('t_object','t_package','t_diagram','t_diagramobjects',
                    't_connector','t_xref','t_objectproperties','t_connectortag','t_genopt'))
REQUIRED = {
    't_package':('Package_ID','Name','Parent_ID','ea_guid'),
    't_object':('Object_ID','Name','Object_Type','Package_ID','ParentID','ea_guid','Stereotype'),
    't_connector':('Connector_ID','Start_Object_ID','End_Object_ID','Connector_Type','ea_guid'),
    't_diagram':('Diagram_ID','Package_ID','Name','ea_guid'),
    't_diagramobjects':('Diagram_ID','Object_ID'),
    't_objectproperties':('Object_ID','Property','Value'),
}
MAX_TEXT=1_000_000


class QEAError(ValueError):
    """Actionable error safe to display without SQL/connection details."""


def local_access_policy(address, environ=None):
    """UI policy; localhost is the default. Shared hosts require an allowlisted root."""
    env=os.environ if environ is None else environ
    if env.get('DIAGRAMGENE_DISABLE_LOCAL_QEA','').lower() in ('1','true','yes'):
        raise QEAError('Pembacaan file QEA dinonaktifkan oleh konfigurasi backend.')
    root=env.get('DIAGRAMGENE_QEA_ROOT','')
    if address not in ('127.0.0.1','localhost','::1') and not root:
        raise QEAError('Backend bersama/non-loopback: akses path QEA dinonaktifkan. Administrator dapat menetapkan DIAGRAMGENE_QEA_ROOT untuk membatasi direktori.')
    return Path(root).expanduser().resolve() if root else None


def probe(path, allowed_root=None):
    try:
        candidate=Path(path).expanduser().resolve(strict=True)
        if allowed_root and not candidate.is_relative_to(Path(allowed_root).resolve()):
            raise QEAError('File berada di luar direktori QEA yang diizinkan backend.')
        info=candidate.stat()
        if not stat.S_ISREG(info.st_mode): raise QEAError('Pilih file QEA biasa, bukan direktori/perangkat.')
        if candidate.suffix.lower()!='.qea':
            raise QEAError('Pembaca langsung saat ini mendukung .qea saja; kompatibilitas .qeax belum diverifikasi.')
        for suffix in ('-wal','-shm','-journal'):
            if Path(str(candidate)+suffix).exists():
                raise QEAError('Repository mempunyai WAL/journal/SHM. Tutup EA dan gunakan repository stabil yang telah diselesaikan SQLite; jangan menyalin atau menghapus sidecar secara manual.')
        with candidate.open('rb') as stream: header=stream.read(100)
        if len(header)!=100 or header[:16]!=b'SQLite format 3\x00':
            raise QEAError('File bukan database SQLite QEA yang valid.')
        if header[18:20]!=b'\x01\x01':
            raise QEAError('Mode WAL/format jurnal SQLite ini belum didukung. Gunakan repository lokal stabil atau snapshot JSON melalui exporter EA.')
        # Nanosecond timestamps/inodes can exceed ES3's exact integer range.
        # Serialize as strings so Python and JScript sign identical plan data.
        signals={'path':str(candidate),'size':info.st_size,'mtime_ns':str(info.st_mtime_ns),
                 'ctime_ns':str(info.st_ctime_ns),'device':str(info.st_dev),'inode':str(info.st_ino),
                 'header_sha256':hashlib.sha256(header).hexdigest(),
                 'change_counter':int.from_bytes(header[24:28],'big')}
        digest=hashlib.sha256(json.dumps(signals,sort_keys=True).encode()).hexdigest()
        return {'path':str(candidate),'fingerprint':digest,'signals':signals}
    except QEAError: raise
    except (OSError,RuntimeError,ValueError) as exc:
        raise QEAError('File QEA tidak ditemukan/tidak dapat dibaca. Path harus berada pada mesin backend DiagramGene.') from exc


class QEAReader:
    def __init__(self,path,allowed_root=None,timeout=10,metadata_bytes=32*1024*1024):
        self.path=path;self.allowed_root=allowed_root;self.timeout=timeout;self.metadata_bytes=metadata_bytes
        self.connection=None;self.schema={};self.start=None
        self.bytes_read=0

    def _authorize(self,action,arg1,arg2,_database,_trigger):
        allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,
                 sqlite3.SQLITE_TRANSACTION,sqlite3.SQLITE_RECURSIVE}
        if action==sqlite3.SQLITE_FUNCTION and str(arg2).lower()=='load_extension':
            return sqlite3.SQLITE_DENY
        if action==sqlite3.SQLITE_PRAGMA and arg1.lower()=='table_info' and arg2.lower() in TABLES:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY

    @contextmanager
    def read(self):
        if self.connection is not None: raise QEAError('Transaksi repository sudah aktif.')
        before=probe(self.path,self.allowed_root)
        try:
            self.connection=sqlite3.connect(Path(before['path']).as_uri()+'?mode=ro',uri=True,timeout=1)
            self.connection.row_factory=sqlite3.Row
            # Some macOS Python builds omit extension-loading support entirely.
            if hasattr(self.connection,'enable_load_extension'):
                self.connection.enable_load_extension(False)
            self.connection.execute('PRAGMA query_only=ON')
            self.connection.execute('PRAGMA trusted_schema=OFF')
            self.connection.execute('PRAGMA cache_size=-4096')
            deadline=time.monotonic()+self.timeout
            self.connection.set_progress_handler(lambda: int(time.monotonic()>deadline),10000)
            self.connection.set_authorizer(self._authorize)
            self.connection.execute('BEGIN')
            self.bytes_read=0
            tables=self.connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND lower(name) IN ("+','.join('?' for _ in TABLES)+')',tuple(TABLES)).fetchall()
            names={r['name'].lower():r for r in tables}
            self.schema={}
            for table in TABLES & names.keys():
                if 'VIRTUAL TABLE' in (names[table]['sql'] or '').upper():
                    raise QEAError('Tabel EA virtual tidak didukung oleh pembaca read-only ini.')
                self.schema[table]={r['name'].lower():r['name'] for r in self.connection.execute('PRAGMA table_info('+table+')')}
            for table,columns in REQUIRED.items():
                if table not in self.schema or any(c.lower() not in self.schema[table] for c in columns):
                    raise QEAError('Skema EA tidak didukung: kolom/tabel wajib tidak tersedia pada '+table+'. Gunakan exporter JSON EA sebagai fallback.')
            self.start=before
            yield self
            after=probe(self.path,self.allowed_root)
            if after['fingerprint']!=before['fingerprint']:
                raise QEAError('Repository berubah selama pembacaan. Hasil dibatalkan; tutup penulisan EA dan analisis ulang.')
        except QEAError: raise
        except sqlite3.Error as exc:
            raise QEAError('SQLite gagal dibaca: repository terkunci, rusak, query terlalu lama, atau skema belum didukung. Tutup EA/penulisan lain dan analisis ulang; gunakan exporter bila perlu.') from exc
        finally:
            if self.connection is not None: self.connection.close()
            self.connection=None

    def column(self,table,name):
        if table not in TABLES or name.lower() not in self.schema.get(table,{}):
            raise QEAError('Kolom repository yang diperlukan belum didukung: '+table+'.'+name)
        return '"'+self.schema[table][name.lower()].replace('"','""')+'"'

    def rows(self,sql,parameters=(),limit=1000):
        result=[];size=0
        for row in self.connection.execute(sql,parameters):
            if len(result)>=limit: raise QEAError('Lingkup melebihi batas metadata. Pilih package yang lebih kecil atau gunakan pagination inspector.')
            values={k.lower():v for k,v in dict(row).items()}
            for value in values.values():
                if isinstance(value,(str,bytes)):
                    size+=len(value.encode('utf-8') if isinstance(value,str) else value)
                    if len(value)>MAX_TEXT: raise QEAError('Properti metadata terlalu besar untuk ekstraksi aman; gunakan lingkup lain atau exporter EA.')
            if self.bytes_read+size>self.metadata_bytes: raise QEAError('Batas memori metadata tercapai. Persempit lingkup package.')
            result.append(values)
        self.bytes_read+=size
        return result

    def bounded_column(self,table,name,alias):
        column=alias+'.'+self.column(table,name)
        return "CASE WHEN typeof("+column+") IN ('text','blob') THEN substr("+column+",1,"+str(MAX_TEXT+1)+') ELSE '+column+' END AS '+self.column(table,name)

    def select(self,table,columns,where='',parameters=(),limit=1000):
        # Identifiers originate only in the static caller contract and introspection.
        available=[c for c in columns if c.lower() in self.schema.get(table,{})]
        if not available: return []
        return self.rows('SELECT '+','.join(self.bounded_column(table,c,'dg') for c in available)+' FROM '+table+' dg '+where,parameters,limit)

    def scope_sql(self):
        return 'WITH RECURSIVE dg_scope(id) AS (SELECT Package_ID FROM t_package WHERE Package_ID=? UNION SELECT p.Package_ID FROM t_package p JOIN dg_scope s ON p.Parent_ID=s.id) '

    def overview(self):
        counts={table:self.connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                for table in ('t_package','t_object','t_diagram','t_connector')}
        stereotypes=self.connection.execute("SELECT COUNT(DISTINCT Stereotype) FROM t_object WHERE COALESCE(Stereotype,'')<>''").fetchone()[0]
        schema_hash=hashlib.sha256(json.dumps(self.schema,sort_keys=True).encode()).hexdigest()
        markers={}
        if {'option','value'} <= self.schema.get('t_genopt',{}).keys():
            for row in self.select('t_genopt',('Option','Value'),'WHERE "Option" IN (?,?)',('RepositoryGUID','ProjectGUID'),10):
                # Observations only: these values may be cloned; never invent an ID.
                from ea_catalogue import guid
                try: markers[row['option']]=guid(row['value'])
                except ValueError: pass
        return {**self.start,'name':Path(self.start['path']).name,'counts':counts,
                'stereotype_count':stereotypes,'schema_fingerprint':schema_hash,
                'captured_at':datetime.now(timezone.utc).isoformat(),'observed_markers':markers,
                'capabilities':{table:sorted(columns) for table,columns in self.schema.items()},
                'consistency':'stable SQLite read transaction; sidecars/WAL rejected'}

    def package_path(self,package_id):
        names=[];seen=set()
        while package_id:
            if package_id in seen or len(seen)>200: raise QEAError('Hierarchy package mengandung siklus/terlalu dalam.')
            seen.add(package_id)
            rows=self.select('t_package',('Name','Parent_ID'),'WHERE Package_ID=?',(package_id,),1)
            if not rows: raise QEAError('Parent package tidak ditemukan; repository tidak konsisten.')
            names.append(rows[0]['name'] or '');package_id=rows[0]['parent_id']
        return ' / '.join(reversed(names))

    def packages(self,search='',offset=0,limit=50,parent_id=None,guid_filter=''):
        if not 1<=limit<=200 or offset<0: raise QEAError('Pagination package tidak valid.')
        where='WHERE instr(lower(COALESCE(Name,\'\')),lower(?))>0';parameters=[search]
        if parent_id is not None: where+=' AND Parent_ID=?';parameters.append(int(parent_id))
        if guid_filter: where+=" AND instr(lower(COALESCE(ea_guid,'')),lower(?))>0";parameters.append(guid_filter)
        rows=self.select('t_package',('Package_ID','Name','Parent_ID','ea_guid'),where+' ORDER BY Name,Package_ID LIMIT ? OFFSET ?',(*parameters,limit,offset),limit)
        for row in rows: row['path']=self.package_path(row['package_id'])
        return rows

    def page(self,section,package_id,search='',ea_type='',stereotype='',guid_filter='',offset=0,limit=50):
        if not 1<=limit<=200 or offset<0: raise QEAError('Pagination inspector tidak valid.')
        cte=self.scope_sql();params=[int(package_id)]
        if section=='elements':
            sql='SELECT Object_ID AS id,ea_guid AS guid,Name,Object_Type AS type,Stereotype,Package_ID,ParentID FROM t_object WHERE Package_ID IN (SELECT id FROM dg_scope)'
            fields={'Name':search,'Object_Type':ea_type,'Stereotype':stereotype,'ea_guid':guid_filter}
        elif section=='diagrams':
            sql='SELECT Diagram_ID AS id,ea_guid AS guid,Name,Package_ID'+(',Diagram_Type AS type' if 'diagram_type' in self.schema['t_diagram'] else '')+' FROM t_diagram WHERE Package_ID IN (SELECT id FROM dg_scope)'
            fields={'Name':search,'ea_guid':guid_filter}
            if 'diagram_type' in self.schema['t_diagram']: fields['Diagram_Type']=ea_type
        elif section=='relationships':
            sql='SELECT c.Connector_ID AS id,c.ea_guid AS guid,c.Connector_Type AS type,c.Start_Object_ID,c.End_Object_ID'+(',c.Name' if 'name' in self.schema['t_connector'] else '')+(',c.Stereotype' if 'stereotype' in self.schema['t_connector'] else '')+' FROM t_connector c WHERE (c.Start_Object_ID IN (SELECT Object_ID FROM t_object WHERE Package_ID IN (SELECT id FROM dg_scope)) OR c.End_Object_ID IN (SELECT Object_ID FROM t_object WHERE Package_ID IN (SELECT id FROM dg_scope)))'
            fields={'c.ea_guid':guid_filter,'c.Connector_Type':ea_type}
            if 'name' in self.schema['t_connector']: fields['c.Name']=search
            if 'stereotype' in self.schema['t_connector']: fields['c.Stereotype']=stereotype
        elif section=='types':
            return self.rows(cte+"SELECT Object_Type AS type,Stereotype,COUNT(*) AS count FROM t_object WHERE Package_ID IN (SELECT id FROM dg_scope) AND instr(lower(COALESCE(Stereotype,'')),lower(?))>0 AND instr(lower(COALESCE(Object_Type,'')),lower(?))>0 GROUP BY Object_Type,Stereotype ORDER BY count DESC LIMIT ? OFFSET ?",(package_id,stereotype,ea_type,limit,offset),limit)
        elif section=='objects':
            columns=['Diagram_ID','Object_ID']+[c for c in ('RectTop','RectLeft','RectRight','RectBottom','ObjectStyle') if c.lower() in self.schema['t_diagramobjects']]
            sql=cte+'SELECT '+','.join(self.bounded_column('t_diagramobjects',c,'o') for c in columns)+' FROM t_diagramobjects o JOIN t_diagram d ON d.Diagram_ID=o.Diagram_ID JOIN t_object e ON e.Object_ID=o.Object_ID WHERE d.Package_ID IN (SELECT id FROM dg_scope)'
            for column,value in [('Name',search),('Object_Type',ea_type),('Stereotype',stereotype),('ea_guid',guid_filter)]:
                if value: sql+=" AND instr(lower(COALESCE(e."+column+",'')),lower(?))>0";params.append(value)
            return self.rows(sql+' ORDER BY d.Diagram_ID,o.Object_ID LIMIT ? OFFSET ?',(*params,limit,offset),limit)
        else: raise QEAError('Bagian inspector tidak dikenal.')
        for column,value in fields.items():
            if value: sql+=" AND instr(lower(COALESCE("+column+",'')),lower(?))>0";params.append(value)
        return self.rows(cte+sql+' ORDER BY id LIMIT ? OFFSET ?',(*params,limit,offset),limit)

    def extract(self,package_id,element_limit=10000,connector_limit=25000):
        """Bounded records, scoped in SQL; no full database materialization."""
        cte=self.scope_sql();params=(int(package_id),)
        packages=self.rows(cte+'SELECT '+','.join(self.bounded_column('t_package',c,'p') for c in ('Package_ID','Name','Parent_ID','ea_guid'))+' FROM t_package p WHERE p.Package_ID IN (SELECT id FROM dg_scope)',params,20000)
        if not packages: raise QEAError('Package tidak ditemukan dalam repository.')
        elements=self.rows(cte+'SELECT '+','.join(self.bounded_column('t_object',c,'o') for c in ('Object_ID','Name','Object_Type','Package_ID','ParentID','ea_guid','Stereotype','Alias','Classifier','Classifier_guid','NType','PDATA1','PDATA2','PDATA3','PDATA4','PDATA5','StateFlags') if c.lower() in self.schema['t_object'])+" FROM t_object o WHERE o.Package_ID IN (SELECT id FROM dg_scope) AND o.Object_Type<>'Package'",params,element_limit)
        connector_columns=('Connector_ID','ea_guid','Name','Connector_Type','Stereotype','Direction','Notes','Start_Object_ID','End_Object_ID','SubType','PDATA1','PDATA2','PDATA3','PDATA4','PDATA5','StyleEx','StateFlags')
        end_fields=('Role','RoleType','RoleNote','Card','Access','Alias','Containment','IsAggregate','IsOrdered','Qualifier','IsNavigable','IsDerived','Style','Constraint','IsOwned','IsDuplicate','IsChangeable')
        connector_columns+=tuple(prefix+name for prefix in ('Source','Dest') for name in end_fields)
        connectors=self.rows(cte+'SELECT '+','.join(self.bounded_column('t_connector',c,'c') for c in connector_columns if c.lower() in self.schema['t_connector'])+' FROM t_connector c WHERE c.Start_Object_ID IN (SELECT Object_ID FROM t_object WHERE Package_ID IN (SELECT id FROM dg_scope)) OR c.End_Object_ID IN (SELECT Object_ID FROM t_object WHERE Package_ID IN (SELECT id FROM dg_scope))',params,connector_limit)
        object_tags=self.rows(cte+'SELECT '+','.join(self.bounded_column('t_objectproperties',c,'p') for c in ('Object_ID','Property','Value','Notes') if c.lower() in self.schema['t_objectproperties'])+' FROM t_objectproperties p JOIN t_object o ON p.Object_ID=o.Object_ID WHERE o.Package_ID IN (SELECT id FROM dg_scope)',params,100000)
        xrefs=[]
        if {'client','name','description'} <= self.schema.get('t_xref',{}).keys():
            xrefs=self.rows(cte+'SELECT x.Client,x.Name,substr(x.Description,1,'+str(MAX_TEXT+1)+') AS Description FROM t_xref x WHERE x.Client COLLATE NOCASE IN (SELECT ea_guid FROM t_object WHERE Package_ID IN (SELECT id FROM dg_scope) UNION SELECT ea_guid FROM t_connector WHERE Start_Object_ID IN (SELECT Object_ID FROM t_object WHERE Package_ID IN (SELECT id FROM dg_scope)) OR End_Object_ID IN (SELECT Object_ID FROM t_object WHERE Package_ID IN (SELECT id FROM dg_scope)))',params,100000)
        connector_tags=[];tag_key=None
        if 't_connectortag' in self.schema:
            tag_key=next((n for n in ('ElementID','ConnectorID') if n.lower() in self.schema['t_connectortag']),None)
            if tag_key and {'property','value'} <= self.schema['t_connectortag'].keys():
                connector_tags=self.rows(cte+'SELECT '+','.join(self.bounded_column('t_connectortag',c,'t') for c in (tag_key,'Property','Value','Notes') if c.lower() in self.schema['t_connectortag'])+' FROM t_connectortag t JOIN t_connector c ON t.'+self.column('t_connectortag',tag_key)+'=c.Connector_ID WHERE c.Start_Object_ID IN (SELECT Object_ID FROM t_object WHERE Package_ID IN (SELECT id FROM dg_scope)) OR c.End_Object_ID IN (SELECT Object_ID FROM t_object WHERE Package_ID IN (SELECT id FROM dg_scope))',params,100000)
        endpoints=self.rows(cte+'SELECT Object_ID,ea_guid FROM t_object WHERE Object_ID IN (SELECT Start_Object_ID FROM t_connector WHERE Start_Object_ID IN (SELECT Object_ID FROM t_object WHERE Package_ID IN (SELECT id FROM dg_scope)) OR End_Object_ID IN (SELECT Object_ID FROM t_object WHERE Package_ID IN (SELECT id FROM dg_scope)) UNION SELECT End_Object_ID FROM t_connector WHERE Start_Object_ID IN (SELECT Object_ID FROM t_object WHERE Package_ID IN (SELECT id FROM dg_scope)) OR End_Object_ID IN (SELECT Object_ID FROM t_object WHERE Package_ID IN (SELECT id FROM dg_scope)))',params,connector_limit*2+element_limit)
        return {'packages':packages,'elements':elements,'connectors':connectors,'object_tags':object_tags,
                'connector_tags':connector_tags,'connector_tag_key':tag_key,'xrefs':xrefs,'endpoints':endpoints,
                'schema':self.schema,'root_id':int(package_id),'overview':self.overview()}
