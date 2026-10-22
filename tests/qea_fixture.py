"""Synthetic EA storage subset; not a capture of a real/customer repository."""
import sqlite3
from uuid import UUID

CAT='{11111111-1111-4111-8111-111111111111}'
ACTOR='{22222222-2222-4222-8222-222222222222}'
PROCESS='{33333333-3333-4333-8333-333333333333}'
OUT='{55555555-5555-4555-8555-555555555555}'
CONNECTOR='{66666666-6666-4666-8666-666666666666}'


def synthetic_guid(number): return '{'+str(UUID(int=number)).upper()+'}'


def make_qea(path, large=0):
    with sqlite3.connect(path) as db:
        db.executescript('''
        CREATE TABLE t_package(Package_ID INTEGER PRIMARY KEY, Name TEXT, Parent_ID INTEGER, ea_guid TEXT);
        CREATE TABLE t_object(Object_ID INTEGER PRIMARY KEY, Name TEXT, Object_Type TEXT, Package_ID INTEGER, ParentID INTEGER, ea_guid TEXT, Stereotype TEXT, Alias TEXT);
        CREATE TABLE t_connector(Connector_ID INTEGER PRIMARY KEY, Start_Object_ID INTEGER, End_Object_ID INTEGER, Connector_Type TEXT, ea_guid TEXT, Name TEXT, Direction TEXT, Notes TEXT, Stereotype TEXT);
        CREATE TABLE t_diagram(Diagram_ID INTEGER PRIMARY KEY, Package_ID INTEGER, Name TEXT, ea_guid TEXT, Diagram_Type TEXT);
        CREATE TABLE t_diagramobjects(Diagram_ID INTEGER, Object_ID INTEGER, RectTop INTEGER, RectLeft INTEGER, RectRight INTEGER, RectBottom INTEGER, ObjectStyle TEXT);
        CREATE TABLE t_objectproperties(Object_ID INTEGER, Property TEXT, Value TEXT, Notes TEXT);
        CREATE TABLE t_connectortag(ElementID INTEGER, Property TEXT, Value TEXT, Notes TEXT);
        CREATE TABLE t_xref(Client TEXT, Name TEXT, Description TEXT);
        CREATE INDEX obj_package ON t_object(Package_ID);
        CREATE INDEX obj_guid ON t_object(ea_guid);
        CREATE INDEX pkg_parent ON t_package(Parent_ID);
        CREATE INDEX conn_source ON t_connector(Start_Object_ID);
        CREATE INDEX conn_target ON t_connector(End_Object_ID);
        CREATE INDEX tag_object ON t_objectproperties(Object_ID);
        CREATE INDEX tag_connector ON t_connectortag(ElementID);
        CREATE INDEX xref_client ON t_xref(Client);
        ''')
        values={}
        for prefix in ('Source','Dest'):
            for field,default in {'Role':'','RoleType':'','RoleNote':'','Card':'','Access':'Public','Alias':'',
                    'Containment':'Unspecified','IsAggregate':0,'IsOrdered':0,'Qualifier':'',
                    'IsNavigable':'Unspecified','IsDerived':0}.items():
                column=prefix+field
                db.execute('ALTER TABLE t_connector ADD COLUMN '+column+(' INTEGER' if isinstance(default,int) else ' TEXT'))
                values[column]=default
        db.executemany('INSERT INTO t_package VALUES(?,?,?,?)',[(1,'Imports',0,OUT),(2,'Holding catalogue',0,CAT)])
        db.executemany('INSERT INTO t_object VALUES(?,?,?,?,?,?,?,?)',[
            (3,'Manager','Actor',2,0,ACTOR,'',''),(5,'Approval','Activity',2,0,PROCESS,'','')])
        columns=['Connector_ID','Start_Object_ID','End_Object_ID','Connector_Type','ea_guid','Name','Direction','Notes','Stereotype']+list(values)
        template='INSERT INTO t_connector('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')'
        db.execute(template,[7,3,5,'Association',CONNECTOR,'bertanggung jawab','Source -> Destination','','']+list(values.values()))
        db.execute('INSERT INTO t_diagram VALUES(1,2,?,?,?)',('Catalogue diagram',synthetic_guid(100),'Logical'))
        db.execute('INSERT INTO t_diagramobjects VALUES(1,3,0,0,100,-100,?)',('',))
        if large:
            db.executemany('INSERT INTO t_package VALUES(?,?,?,?)',[(10+i,'OPCO '+str(i),2,synthetic_guid(1000+i)) for i in range(100)])
            db.executemany('INSERT INTO t_object VALUES(?,?,?,?,?,?,?,?)',[
                (100+i,'Actor '+str(i),'Actor',10+i%100,0,synthetic_guid(10000+i),'','') for i in range(large)])
            db.executemany(template,[[100+i,100+i,100+(i+1)%large,'Association',synthetic_guid(100000+i),'link '+str(i),'Source -> Destination','','']+list(values.values()) for i in range(large)])
            db.executemany('INSERT INTO t_diagram VALUES(?,?,?,?,?)',[(100+i,10+i,'Diagram '+str(i),synthetic_guid(200000+i),'Logical') for i in range(100)])
            db.executemany('INSERT INTO t_diagramobjects VALUES(?,?,0,0,100,-100,?)',[(100+i%100,100+i,'') for i in range(large)])
    return path
