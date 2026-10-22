// Two phases: read-only verification, then optional execution. No rollback/delete.
var dgCreated=[], dgResolved={}, dgConnectors={}, dgPackages={}, dgCatalogue={}, dgTarget=null;
function dgFail(message){throw new Error(message);}
function dgUpper(value){return String(value||'').toUpperCase();}
function dgLog(value){Session.Output(typeof value=='string'?value:dgJson(value));}
function dgFindNode(id){for(var i=0;i<PLAN.nodes.length;i++){if(PLAN.nodes[i].id==id){return PLAN.nodes[i];}}dgFail('Unresolved source identity.');}
function dgStereotypes(value){var out=String(value||'').split(',');for(var i=0;i<out.length;i++){out[i]=out[i].replace(/^\s+|\s+$/g,'');}out.sort();return out.join(',');}
function dgQualified(element,type){return type.indexOf('::')<0?String(element.Type)==type&&!String(element.StereotypeEx||''):(','+dgStereotypes(element.StereotypeEx)+',').indexOf(','+type+',')>=0;}
function dgCollectCatalogue(root){
    var stack=[root], seen={};
    while(stack.length){var pkg=stack.pop();dgPackages[dgUpper(pkg.PackageGUID)]=pkg;
        var work=[];for(var j=0;j<pkg.Elements.Count;j++){work.push(pkg.Elements.GetAt(j));}
        while(work.length){var el=work.pop(),key=dgUpper(el.ElementGUID);if(seen[key]){continue;}seen[key]=true;dgCatalogue[key]=el;
            for(var k=0;k<el.Elements.Count;k++){work.push(el.Elements.GetAt(k));}}
        for(var i=0;i<pkg.Packages.Count;i++){stack.push(pkg.Packages.GetAt(i));}}
}
function dgInScope(element,scopeGuid){
    var pkg=Repository.GetPackageByID(element.PackageID),seen={};
    while(pkg){var key=dgUpper(pkg.PackageGUID);if(key==scopeGuid){return true;}if(seen[key]){dgFail('Package cycle.');}seen[key]=true;
        if(!pkg.ParentID){return false;}pkg=Repository.GetPackageByID(pkg.ParentID);}
    return false;
}
function dgTagValue(element,name){var found='';for(var i=0;i<element.TaggedValues.Count;i++){var tag=element.TaggedValues.GetAt(i);if(String(tag.Name)==name){if(String(tag.Value)=='<memo>'){dgFail('Memo business identifier unsupported.');}found=String(tag.Value);}}return found;}
function dgCheckMaster(node,element){
    var expected=node.master;if(!expected){dgFail('Master snapshot missing.');}
    if(element.ElementID!=expected.id||dgUpper(element.ElementGUID)!=node.master_guid||!dgQualified(element,node.ea_type)||String(element.Type)!=expected.base_type||dgStereotypes(element.StereotypeEx)!=dgStereotypes(expected.stereotype)){
        dgFail('Master GUID/base type/qualified stereotype changed: '+node.id);}
    if(dgUpper(Repository.GetPackageByID(element.PackageID).PackageGUID)!=expected.package_guid){dgFail('Master package changed: '+node.id);}
    var parent=element.ParentID?dgUpper(Repository.GetElementByID(element.ParentID).ElementGUID):'';
    if(parent!=expected.parent_guid){dgFail('Master parent changed: '+node.id);}
    var scope=PLAN.profile.scope_package_guid||PLAN.profile.catalogue_root_guid;
    if(!dgInScope(element,scope)){dgFail('Master outside approved package scope: '+node.id);}
    var opco=PLAN.profile.opco||node.opco;
    if(opco&&(dgTagValue(element,'DG_OPCO')||dgTagValue(element,'OPCO'))!=opco){dgFail('Master OPCO scope mismatch.');}
    if(expected.business_id&&(dgTagValue(element,'DG_BusinessID')||dgTagValue(element,'BusinessID'))!=expected.business_id){dgFail('Stable business identifier changed.');}
    var semanticTags=['eventDefinition','gatewayType','activityType','isInterrupting'];
    if(node.ea_type.indexOf('BPMN2.0::')==0&&(!expected.element_tags_hash||dgSha256(dgJson(dgTags(element)))!=expected.element_tags_hash)){dgFail('BPMN semantic references/tagged values changed or unavailable.');}
    for(var t=0;t<semanticTags.length;t++){var tag=semanticTags[t];if(expected.tags&&typeof expected.tags[tag]!='undefined'&&dgTagValue(element,tag)!=expected.tags[tag]){dgFail('BPMN semantic tagged value changed: '+tag);}}
    if(node.resolution_basis!='guid'){
        var count=0;for(var id in dgCatalogue){if(!Object.prototype.hasOwnProperty.call(dgCatalogue,id)){continue;}var candidate=dgCatalogue[id];
            if(!dgQualified(candidate,node.ea_type)||!dgInScope(candidate,scope)){continue;}
            if(opco&&(dgTagValue(candidate,'DG_OPCO')||dgTagValue(candidate,'OPCO'))!=opco){continue;}
            if(node.resolution_basis=='business_id'?(dgTagValue(candidate,'DG_BusinessID')||dgTagValue(candidate,'BusinessID'))==node.business_id:
                String(candidate.Name).replace(/\s+/g,' ').replace(/^\s+|\s+$/g,'').toLowerCase()==node.name.replace(/\s+/g,' ').replace(/^\s+|\s+$/g,'').toLowerCase()){count++;}}
        if(count!=1){dgFail('Live catalogue matching became ambiguous/missing; refresh snapshot and bind an explicit GUID.');}}
}
function dgConnectorSignature(c){var out={};var keys=['source_guid','target_guid','base_type','stereotype','name','direction','source_role','target_role','tags_hash','notes_hash'];
    for(var i=0;i<keys.length;i++){out[keys[i]]=c[keys[i]];}return out;}
function dgRuntimeBpmn(r,src,tgt){
    var source=dgFindNode(r.source),target=dgFindNode(r.target),type=r.relationship_type;
    if(type=='BPMN: Sequence Flow'){
        if(!source.pool||source.pool!=target.pool||source.process_scope!=target.process_scope){dgFail('Invalid BPMN cross-pool/subprocess Sequence Flow.');}
        if(source.kind=='end'||target.kind=='start'){dgFail('Invalid BPMN start/end direction.');}}
    if(type=='BPMN: Message Flow'&&(!source.pool||!target.pool||source.pool==target.pool)){dgFail('Invalid BPMN Message Flow participant boundaries.');}
}
function dgPreflight(){
    var digestCopy={},key;for(key in PLAN){if(Object.prototype.hasOwnProperty.call(PLAN,key)&&key!='plan_digest'&&key!='approval_digest'){digestCopy[key]=PLAN[key];}}
    if(dgSha256(dgJson(digestCopy))!=PLAN.plan_digest){dgFail('Plan digest mismatch: regenerate and reapprove current plan.');}
    var actual=dgIdentity(Repository);
    if(!PLAN.profile.expected_identity||dgJson(actual)!=dgJson(PLAN.profile.expected_identity)){dgFail('Active repository identity does not match the selected profile.');}
    if(PLAN.profile.environment=='production'&&actual.kind!='server'){dgFail('Production profile cannot execute against a local clone.');}
    if(PLAN.profile.environment=='local'&&actual.kind!='local'){dgFail('Local Testing cannot execute against a server repository.');}
    if(PLAN.repository_source&&PLAN.repository_source.trusted_capture){
        if(PLAN.profile.environment!='local'||!PLAN.profile.qea_identity_reviewed){dgFail('Direct QEA identity binding requires reviewed local Wine locator; no production authorization.');}
        dgLog({phase:'IDENTITY_SCOPE',confidence:PLAN.repository_source.identity_confidence,
            limitation:'Locator/model metadata checks are not a globally unique repository identity or an atomic file-freshness proof.'});}
    if(PLAN.errors.length){dgFail('Plan validation: '+PLAN.errors.join(' | '));}
    dgTarget=PLAN.profile.output_package_guid?Repository.GetPackageByGuid(PLAN.profile.output_package_guid):Repository.GetTreeSelectedPackage();
    if(!dgTarget){dgFail('Output package missing; no writes performed.');}
    if(PLAN.profile.environment=='production'&&!PLAN.profile.output_package_guid){dgFail('Production requires a pinned output package GUID.');}
    if(PLAN.profile.catalogue_root_guid){var root=Repository.GetPackageByGuid(PLAN.profile.catalogue_root_guid);if(!root){dgFail('Catalogue root not found.');}dgCollectCatalogue(root);}
    if(PLAN.profile.scope_package_guid&&!dgPackages[PLAN.profile.scope_package_guid]){dgFail('Approved scope is outside catalogue.');}
    for(var t=0;t<PLAN.required_technologies.length;t++){
        var available=false;try{available=Repository.IsTechnologyEnabled(PLAN.required_technologies[t]);}catch(e){dgFail('Cannot verify MDG availability through Automation API.');}
        if(!available){dgFail('Required MDG unavailable: '+PLAN.required_technologies[t]);}}
    var perPage={};
    for(var i=0;i<PLAN.nodes.length;i++){var node=PLAN.nodes[i];
        if(node.status!='NEW'&&node.status!='REUSE'){dgFail('Unresolved/review/blocked element: '+node.id+' '+node.reason);}
        if(node.status=='NEW'){
            if(!node.approved_new||!PLAN.profile.allow_new_elements||node.requires_master){dgFail('Unapproved new element: '+node.id);}
            if(!node.distinct_object_confirmed){for(var candidateId in dgCatalogue){if(!Object.prototype.hasOwnProperty.call(dgCatalogue,candidateId)){continue;}var candidate=dgCatalogue[candidateId];
                var nodeScope=PLAN.profile.scope_package_guid||PLAN.profile.catalogue_root_guid,opco=PLAN.profile.opco||node.opco;
                if(!dgQualified(candidate,node.ea_type)||!dgInScope(candidate,nodeScope)){continue;}
                if(opco&&(dgTagValue(candidate,'DG_OPCO')||dgTagValue(candidate,'OPCO'))!=opco){continue;}
                if(node.business_id?(dgTagValue(candidate,'DG_BusinessID')||dgTagValue(candidate,'BusinessID'))==node.business_id:
                   String(candidate.Name).replace(/\s+/g,' ').replace(/^\s+|\s+$/g,'').toLowerCase()==node.name.replace(/\s+/g,' ').replace(/^\s+|\s+$/g,'').toLowerCase()){
                    dgFail('A catalogue candidate exists/appeared for NEW; refresh, reuse or explicitly confirm distinct identity.');}}}
            continue;}
        var el=dgCatalogue[node.master_guid];if(!el){dgFail('Master GUID not found inside live catalogue: '+node.id);}dgCheckMaster(node,el);dgResolved[node.id]=el;
        var collision=node.source_page_id+'|'+node.master_guid;
        if(perPage[collision]&&(!node.same_master_confirmed||!perPage[collision].same_master_confirmed)){dgFail('Distinct source elements collapse into one master without confirmation.');}
        perPage[collision]=node;
    }
    for(var p=0;p<PLAN.nodes.length;p++){var n=PLAN.nodes[p];
        if(n.ea_type.indexOf('BPMN2.0::')==0&&n.status=='REUSE'){
            var master=dgResolved[n.id];
            if(n.kind=='pool'){if(master.ParentID){dgFail('Pool owning process context is unsupported.');}}
            else{var owner=dgResolved[n.parent];if(!owner||master.ParentID!=owner.ElementID){dgFail('Wrong Pool/Lane/subprocess parent for reused BPMN object.');}}}}
    for(var j=0;j<PLAN.relationships.length;j++){var r=PLAN.relationships[j];
        var srcNode=dgFindNode(r.source),tgtNode=dgFindNode(r.target),src=dgResolved[r.source],tgt=dgResolved[r.target];
        if(r.action!='REUSE'&&r.action!='PROPOSE_CREATE'){dgFail('Relationship unresolved/blocked: '+r.id+' '+r.reason);}
        if(!r.semantic_confirmed){dgFail('Relationship semantics unconfirmed.');}
        if(src&&tgt&&src.ElementID==tgt.ElementID&&r.source!=r.target){dgFail('Wrong source/target master mapping collapse.');}
        dgRuntimeBpmn(r,src,tgt);
        if(r.action=='REUSE'){
            var connector=Repository.GetConnectorByGuid(r.existing_connector_guid||r.expected_connector.guid);
            if(!connector){dgFail('Approved ConnectorGUID not found.');}
            var observed=dgConnector(connector);
            if(!src||!tgt||connector.ConnectorID!=r.expected_connector.id||connector.ClientID!=src.ElementID||connector.SupplierID!=tgt.ElementID||dgJson(dgConnectorSignature(observed))!=dgJson(dgConnectorSignature(r.expected_connector))){dgFail('Connector GUID/endpoint/role/tag/semantic signature changed.');}
            dgConnectors[r.id]=connector;
        } else {
            if(PLAN.mode=='EXECUTE'&&!r.approved_create){dgFail('New relationship lacks per-relationship approval: '+r.id);}
            // Another import might have added a connector since the snapshot. Never duplicate it.
            if(src&&tgt){for(var c=0;c<src.Connectors.Count;c++){var current=src.Connectors.GetAt(c);
                if(current.ClientID==src.ElementID&&current.SupplierID==tgt.ElementID&&String(current.Type)==r.base_type&&String(current.Name||'')==r.name&&String(current.Direction)==r.direction&&dgStereotypes(current.StereotypeEx)==dgStereotypes(r.stereotype)){
                    dgFail('A possibly equivalent connector now exists; refresh snapshot and approve its ConnectorGUID.');}}}
        }
    }
    dgLog({phase:'PREFLIGHT',mode:PLAN.mode,elements:PLAN.summary,relationships:PLAN.relationship_summary,plan_digest:PLAN.plan_digest});
    if(PLAN.mode=='EXECUTE'&&(!PLAN.can_execute||PLAN.approval_digest!=PLAN.plan_digest)){dgFail('Execution was not explicitly approved for this exact plan.');}
}
function dgTrack(object,kind){
    var record={kind:kind,name:String(object.Name||''),id:object.ElementID||object.ConnectorID||object.DiagramID||object.PackageID||0,
        guid:String(object.ElementGUID||object.ConnectorGUID||object.DiagramGUID||object.PackageGUID||'')};dgCreated.push(record);
    if(!object.Update()){dgFail('Update failed for '+kind+'; see created-object ledger.');}
    record.id=object.ElementID||object.ConnectorID||object.DiagramID||object.PackageID||0;
    record.guid=String(object.ElementGUID||object.ConnectorGUID||object.DiagramGUID||object.PackageGUID||'');return object;
}
function dgCreateNode(node,pkg){
    if(dgResolved[node.id]){return dgResolved[node.id];}
    // Generic visual containment is not an instruction to change EA ownership.
    var owner=node.parent&&node.ea_type.indexOf('BPMN2.0::')==0?dgCreateNode(dgFindNode(node.parent),pkg):pkg;
    var el=dgTrack(owner.Elements.AddNew(node.name.replace(/\n/g,' '),node.ea_type),'element');
    if(!dgQualified(el,node.ea_type)){dgFail('EA did not apply required element type/stereotype; no fallback permitted.');}
    if(node.ea_type=='Note'||node.kind=='annotation'||node.name.indexOf('\n')>=0){
        el.Notes=node.name.replace(/\n/g,'\r\n');if(!el.Update()){dgFail('New element annotation/text update failed.');}}
    el.TaggedValues.Refresh();
    var requested={};
    if(node.ea_type.indexOf('BPMN2.0::')==0){
        if(node.kind=='subprocess'){requested.activityType='Sub-Process';}
        if(node.gateway_type){requested.gatewayType=node.gateway_type;}
        if(node.event_definition&&node.event_definition!='None'){requested.eventDefinition=node.event_definition;}
        for(var name in requested){if(!Object.prototype.hasOwnProperty.call(requested,name)){continue;}var found=null;
            for(var t=0;t<el.TaggedValues.Count;t++){if(String(el.TaggedValues.GetAt(t).Name)==name){found=el.TaggedValues.GetAt(t);break;}}
            if(!found){dgFail('Required native BPMN MDG tag unavailable: '+name+'; inspect created-object ledger.');}
            found.Value=requested[name];if(!found.Update()){dgFail('New element BPMN tag update failed.');}}}
    var identifiers={DG_BusinessID:node.business_id||'',DG_OPCO:PLAN.profile.opco||node.opco||''};
    for(var identifier in identifiers){if(Object.prototype.hasOwnProperty.call(identifiers,identifier)&&identifiers[identifier]){
        var tag=el.TaggedValues.AddNew(identifier,identifiers[identifier]);tag.Value=identifiers[identifier];if(!tag.Update()){dgFail('New element identifier tag update failed.');}}}
    dgResolved[node.id]=el;return el;
}
function dgSetEnd(end,values){for(var key in values){if(Object.prototype.hasOwnProperty.call(values,key)&&key!='role_note_hash'){end[key]=values[key];}}
    if(!end.Update()){dgFail('New connector end update failed.');}}
function dgCreateConnector(r){
    if(dgConnectors[r.id]){return dgConnectors[r.id];}
    if(r.reuse_planned_relation&&dgConnectors[r.reuse_planned_relation]){dgConnectors[r.id]=dgConnectors[r.reuse_planned_relation];return dgConnectors[r.id];}
    var src=dgResolved[r.source],tgt=dgResolved[r.target];if(!src||!tgt){dgFail('Endpoint unresolved after node creation.');}
    var c=src.Connectors.AddNew(r.name,r.base_type);
    // AddNew may already persist an object: record before Update as well.
    var record={kind:'connector',name:r.name,id:c.ConnectorID,guid:String(c.ConnectorGUID||'')};dgCreated.push(record);
    c.SupplierID=tgt.ElementID;c.Direction=r.direction;c.StereotypeEx=r.stereotype;
    if(!c.Update()){dgFail('Connector update failed.');}
    record.id=c.ConnectorID;record.guid=String(c.ConnectorGUID||'');
    dgSetEnd(c.ClientEnd,r.source_role);dgSetEnd(c.SupplierEnd,r.target_role);
    for(var key in r.tags){if(Object.prototype.hasOwnProperty.call(r.tags,key)){var tag=null;
        for(var t=0;t<c.TaggedValues.Count;t++){if(String(c.TaggedValues.GetAt(t).Name)==key){if(tag){dgFail('Ambiguous new connector tag.');}tag=c.TaggedValues.GetAt(t);}}
        if(!tag&&r.relationship_type=='ArchiMate: Access'){dgFail('Native ArchiMate Access metadata unavailable; inspect created-object ledger.');}
        tag=tag||c.TaggedValues.AddNew(key,String(r.tags[key]));tag.Value=String(r.tags[key]);if(!tag.Update()){dgFail('Connector tag update failed.');}}}
    if(String(c.Type)!=r.base_type||dgStereotypes(c.StereotypeEx)!=dgStereotypes(r.stereotype)){dgFail('EA connector type/stereotype mismatch; inspect ledger.');}
    var expected={source_guid:dgUpper(src.ElementGUID),target_guid:dgUpper(tgt.ElementGUID),base_type:r.base_type,stereotype:r.stereotype,name:r.name,direction:r.direction,
        source_role:r.source_role,target_role:r.target_role,notes_hash:r.notes_hash,tags_hash:dgSha256(dgJson((function(){var out=[];for(var k in r.tags){if(Object.prototype.hasOwnProperty.call(r.tags,k)){out.push([k,String(r.tags[k])]);}}out.sort(function(a,b){return dgJson(a)<dgJson(b)?-1:dgJson(a)>dgJson(b)?1:0;});return out;})()))};
    if(dgJson(dgConnectorSignature(dgConnector(c)))!=dgJson(expected)){dgFail('Created connector semantic metadata differs; inspect ledger and reconcile manually.');}
    dgConnectors[r.id]=c;return c;
}
function dgExecute(){
    for(var p=0;p<PLAN.pages.length;p++){var page=PLAN.pages[p],pkg=dgTrack(dgTarget.Packages.AddNew(page.name,''),'package');
        var dia=dgTrack(pkg.Diagrams.AddNew(page.name,page.diagram_type),'diagram'), placed={},links={};
        for(var i=0;i<PLAN.nodes.length;i++){var node=PLAN.nodes[i];if(node.source_page_id!=page.id){continue;}
            var el=dgCreateNode(node,pkg);if(placed[el.ElementID]){continue;}placed[el.ElementID]=true;
            var g=node.geometry,pos='l='+g.l+';r='+g.r+';t='+g.t+';b='+g.b+';';
            var object=dia.DiagramObjects.AddNew(pos,'');object.ElementID=el.ElementID;
            object.Sequence=node.kind=='pool'?100:node.kind=='lane'?50:1;dgTrack(object,'diagram-object');}
        for(var j=0;j<PLAN.relationships.length;j++){var r=PLAN.relationships[j];if(dgFindNode(r.source).source_page_id!=page.id){continue;}
            var connector=dgCreateConnector(r);if(links[connector.ConnectorID]){continue;}links[connector.ConnectorID]=true;
            var link=dia.DiagramLinks.AddNew('','');link.ConnectorID=connector.ConnectorID;dgTrack(link,'diagram-link');}
        Repository.RefreshModelView(pkg.PackageID);
    }
    dgLog({phase:'EXECUTED',created:dgCreated,limitation:'New output packages/diagrams are created per import. No full synchronization or rollback.'});
}
function dgMain(){
    try{dgPreflight();if(PLAN.mode=='VALIDATE_ONLY'){dgLog('VALIDATE_ONLY: repository unchanged.');return;}dgExecute();}
    catch(e){dgLog({phase:dgCreated.length?'WRITE_FAILURE':'PREFLIGHT_FAILURE',created:dgCreated,message:String(e.message||e),rollback:false});throw e;}
}
dgMain();
