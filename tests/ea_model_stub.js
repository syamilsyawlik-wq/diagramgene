// Contract fixture, NOT an EA implementation. Unknown API/mutators fail explicitly.
const fs=require('fs'),vm=require('vm');let script=fs.readFileSync(0,'utf8'),fixture={};
if(script.trimStart().startsWith('{')){const input=JSON.parse(script);script=input.script;fixture=input.fixture||{};}
let nextId=1,running=false,mutationAttempts=0;
const elements=[],connectors=[],diagramObjects=[],diagramLinks=[],packages=[],diagrams=[],logs=[];
const guid=()=>'{00000000-0000-4000-8000-'+String(nextId++).padStart(12,'0')+'}';
const baseTypes=new Set(['Class','Component','Node','Artifact','Interface','Actor','Activity','UseCase','Decision','Boundary','Note','ActivityPartition','StateNode','Requirement']);
const mdg={
 'BPMN2.0::Pool':'ActivityPartition','BPMN2.0::Lane':'ActivityPartition','BPMN2.0::Activity':'Activity','BPMN2.0::Gateway':'Decision',
 'BPMN2.0::StartEvent':'StateNode','BPMN2.0::EndEvent':'StateNode','BPMN2.0::IntermediateEvent':'StateNode','BPMN2.0::DataObject':'Artifact','BPMN2.0::TextAnnotation':'Note'};
const arch={BusinessActor:'Actor',BusinessRole:'Class',BusinessProcess:'Activity',BusinessService:'Class',BusinessObject:'Class',ApplicationComponent:'Component',ApplicationService:'Class',ApplicationFunction:'Activity',ApplicationInterface:'Interface',DataObject:'Class',Node:'Node',Device:'Node',SystemSoftware:'Node',CommunicationNetwork:'Class',TechnologyService:'Class',Artifact:'Artifact',Capability:'Class',Goal:'Class',Requirement:'Requirement',WorkPackage:'Activity'};
for(const [name,type] of Object.entries(arch)){mdg['ArchiMate3::ArchiMate_'+name]=type;}
const connectorMdg={'BPMN2.0::SequenceFlow':'ControlFlow','BPMN2.0::MessageFlow':'ControlFlow','BPMN2.0::DataAssociation':'Dependency','BPMN2.0::Association':'Association'};
for(const [name,type] of Object.entries({Assignment:'Association',Association:'Association',Serving:'Dependency',Access:'Dependency',Realization:'Realisation',Flow:'Dependency',Triggering:'Dependency'})){connectorMdg['ArchiMate3::ArchiMate_'+name]=type;}
function mutate(){if(running){mutationAttempts++;if(fixture.rejectWrites){throw Error('Mutation forbidden by fixture.');}}}
function updateable(object={},kind='',validate=()=>{}){return Object.assign(object,{UpdateCalls:0,Update(){mutate();this.UpdateCalls++;validate(this);return fixture.failUpdateKind!==kind;},GetLastError(){return 'fixture update failure';}});}
function collection(add){const values=[];return {values,get Count(){return values.length;},GetAt(i){if(i<0||i>=values.length){throw Error('GetAt out of range');}return values[i];},AddNew(...args){mutate();const v=add(...args);values.push(v);return v;},Refresh(){}};}
function tags(seed={}){const c=collection((name,value)=>updateable({Name:name,Value:value,Notes:''},'tag'));
 for(const [name,value] of Object.entries(seed)){c.values.push(updateable({Name:name,Value:String(value),Notes:''},'tag'));}return c;}
function end(seed={}){return updateable(Object.assign({Role:'',Cardinality:'',Aggregation:0,Navigable:'Unspecified',RoleType:'',Alias:'',Qualifier:'',Containment:'Unspecified',Visibility:'Public',Derived:false,Ordering:0,RoleNote:''},seed),'connector-end');}
function element(name,type,owner,parentId=0){if(!baseTypes.has(type)&&!mdg[type]){throw Error('Unsupported element Type: '+type);}
 const id=nextId++,qualified=!!mdg[type];const el=updateable({Name:name,Type:mdg[type]||type,ElementID:id,PackageID:owner.PackageID,ParentID:parentId,
 ElementGUID:guid(),Alias:'',StereotypeEx:qualified?type:'',Notes:'',TaggedValues:tags()},'element');
 el.Elements=collection((n,t)=>element(n,t,owner,el.ElementID));
 el.Connectors=collection((label,t)=>{
   if(!['Association','Dependency','ControlFlow','Realisation','Generalization'].includes(t)){throw Error('Unsupported connector base Type: '+t);}
   const c=updateable({Name:label,Notes:'',Type:t,ConnectorID:nextId++,ConnectorGUID:guid(),ClientID:id,SupplierID:0,Direction:'Unspecified',StereotypeEx:'',
     ClientEnd:end(),SupplierEnd:end(),TaggedValues:tags()},'connector',o=>{
       if(!elements.some(e=>e.ElementID===o.SupplierID)){throw Error('Missing supplier endpoint');}
       if(!['Unspecified','Source -> Destination','Bi-Directional'].includes(o.Direction)){throw Error('Unsupported direction');}
       if(o.StereotypeEx.includes('::')&&connectorMdg[o.StereotypeEx]!==o.Type){throw Error('Unsupported connector qualified stereotype/base Type');}});
   connectors.push(c);return c;});elements.push(el);return el;}
function diagram(name,type){if(!['Custom','Logical','BPMN2.0::Business Process','Analysis','Component','Use Case'].includes(type)){throw Error('Unsupported diagram Type');}
 const d=updateable({Name:name,Type:type,DiagramID:nextId++,DiagramGUID:guid()},'diagram');diagrams.push(d);
 d.DiagramObjects=collection(position=>{if(!/^l=-?\d+;r=-?\d+;t=-?\d+;b=-?\d+;$/.test(position)){throw Error('Invalid diagram geometry');}
  const o=updateable({position,DiagramID:d.DiagramID,ElementID:0},'diagram-object',v=>{if(!elements.some(e=>e.ElementID===v.ElementID)){throw Error('Missing diagram element');}
   if(diagramObjects.some(x=>x!==v&&x.DiagramID===v.DiagramID&&x.ElementID===v.ElementID)){throw Error('Duplicate element placement');}});diagramObjects.push(o);return o;});
 d.DiagramLinks=collection(()=>{const l=updateable({DiagramID:d.DiagramID,ConnectorID:0},'diagram-link',o=>{const c=connectors.find(c=>c.ConnectorID===o.ConnectorID);
  if(!c){throw Error('Missing diagram connector');}const shown=diagramObjects.filter(x=>x.DiagramID===d.DiagramID).map(x=>x.ElementID);
  if(!shown.includes(c.ClientID)||!shown.includes(c.SupplierID)){throw Error('Connector endpoints not displayed');}});diagramLinks.push(l);return l;});return d;}
function pkg(name='',pguid='',seeded=false,parent=0){const p=updateable({Name:name,PackageID:nextId++,PackageGUID:pguid||guid(),ParentID:parent,seeded},'package');
 p.Packages=collection(n=>pkg(n,'',false,p.PackageID));p.Elements=collection((n,t)=>element(n,t,p));p.Diagrams=collection(diagram);packages.push(p);return p;}
function seedPackage(seed,parent=0){const p=pkg(seed.name,seed.guid,true,parent);
 for(const item of seed.elements||[]){const el=p.Elements.AddNew(item.name,item.type);Object.assign(el,{ElementGUID:item.guid,Notes:item.notes||'',Alias:item.alias||'',StereotypeEx:item.stereotype||'',seeded:true,_parentGuid:item.parent_guid||'',TaggedValues:tags(item.tags)});}
 for(const child of seed.children||[]){p.Packages.values.push(seedPackage(child,p.PackageID));}return p;}
const target=pkg('Import target',fixture.targetGuid||'{55555555-5555-4555-8555-555555555555}',true);
for(const seed of fixture.packages||[]){seedPackage(seed);}
for(const el of elements){if(el._parentGuid){const parent=elements.find(e=>e.ElementGUID===el._parentGuid);if(!parent){throw Error('Bad seed parent');}el.ParentID=parent.ElementID;parent.Elements.values.push(el);}}
for(const seed of fixture.connectors||[]){const src=elements.find(e=>e.ElementGUID===seed.source),tgt=elements.find(e=>e.ElementGUID===seed.target);if(!src||!tgt){throw Error('Bad seed connector');}
 const c=src.Connectors.AddNew(seed.name||'',seed.type||'Association');Object.assign(c,{ConnectorGUID:seed.guid||c.ConnectorGUID,SupplierID:tgt.ElementID,Notes:seed.notes||'',Direction:seed.direction||'Unspecified',StereotypeEx:seed.stereotype||'',seeded:true,
 ClientEnd:end(seed.source_role),SupplierEnd:end(seed.target_role),TaggedValues:tags(seed.tags)});tgt.Connectors.values.push(c);}
const repo={ConnectionString:fixture.connectionString||'Z:/EA/testing.qea',EnsureOutputVisible(){},ClearOutput(){},RefreshModelView(){},OpenDiagram(){},
 GetTreeSelectedPackage(){return fixture.selectedPackageGuid?packages.find(p=>p.PackageGUID===fixture.selectedPackageGuid):target;},
 GetPackageByGuid(g){return packages.find(p=>p.PackageGUID.toUpperCase()===g.toUpperCase())||null;},
 GetPackageByID(id){const p=packages.find(p=>p.PackageID===id);if(!p){throw Error('Package ID missing');}return p;},
 GetElementByID(id){const e=elements.find(e=>e.ElementID===id);if(!e){throw Error('Element ID missing');}return e;},
 GetElementByGuid(g){return elements.find(e=>e.ElementGUID.toUpperCase()===g.toUpperCase())||null;},
 GetConnectorByGuid(g){return connectors.find(c=>c.ConnectorGUID.toUpperCase()===g.toUpperCase())||null;},
 IsTechnologyEnabled(name){return (fixture.technologies||['BPMN2.0','ArchiMate3']).includes(name);}};
const context={Session:{Output(message){logs.push(message);}},Repository:new Proxy(repo,{get(o,k){if(!(k in o)){throw Error('Unsupported Repository API: '+k);}return o[k];}})};
let error=null;running=true;try{for(let run=0;run<(fixture.runs||1);run++){vm.runInNewContext(script,context,{timeout:10000});}}catch(e){error=e.message;}
process.stdout.write(JSON.stringify({elements,connectors,diagramObjects,diagramLinks,diagrams,mutationAttempts,
 packages:packages.map(p=>({Name:p.Name,PackageID:p.PackageID,PackageGUID:p.PackageGUID,ParentID:p.ParentID,seeded:p.seeded})),logs,error}));
if(error&&!fixture.expectError){process.exitCode=1;}
