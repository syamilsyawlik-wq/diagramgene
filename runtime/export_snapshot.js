function main() {
    var root=Repository.GetTreeSelectedPackage();
    if(!root){throw new Error('Pilih root package katalog.');}
    var identity=dgIdentity(Repository), snapshot={format:'diagramgene.catalogue',schema_version:2,
        repository_identity:identity,exported_at:(new Date()).toUTCString(),package_guid:String(root.PackageGUID).toUpperCase(),
        packages:[],elements:[],connectors:[]};
    var packages=[{pkg:root,parent:'',path:String(root.Name)}], seenElements={}, seenConnectors={}, byId={};
    var tagNames=['BusinessID','OPCO','DG_BusinessID','DG_OPCO','eventDefinition','gatewayType','activityType','isInterrupting','accessType'];
    while(packages.length){var current=packages.pop(),pkg=current.pkg;
        snapshot.packages.push({guid:String(pkg.PackageGUID).toUpperCase(),id:pkg.PackageID,parent_guid:current.parent,name:String(pkg.Name),path:current.path});
        var stack=[];for(var i=0;i<pkg.Elements.Count;i++){stack.push(pkg.Elements.GetAt(i));}
        while(stack.length){var el=stack.pop(),key=String(el.ElementGUID).toUpperCase();if(seenElements[key]){continue;}seenElements[key]=true;byId[el.ElementID]=el;
            var tags={},references={},tagsHash='';for(var t=0;t<el.TaggedValues.Count;t++){var tag=el.TaggedValues.GetAt(t);for(var n=0;n<tagNames.length;n++){if(tag.Name==tagNames[n]){tags[tag.Name]=String(tag.Value);}}
                var refName=String(tag.Name).toLowerCase().replace(/[^a-z]/g,'');
                if(/^(processref|participantref|partitionelement|partitionelementref|partnerentity|partnerrole|calledactivity)$/.test(refName)&&String(tag.Value)&&!/^(0|none|<none>)$/i.test(String(tag.Value))){references[String(tag.Name)]=String(tag.Value);}}
            if(String(el.StereotypeEx).indexOf('BPMN2.0::')>=0){try{tagsHash=dgSha256(dgJson(dgTags(el)));}catch(metadataError){tagsHash='';}}
            var parent='';if(el.ParentID){parent=String(Repository.GetElementByID(el.ParentID).ElementGUID).toUpperCase();}
            snapshot.elements.push({guid:key,id:el.ElementID,name:String(el.Name),alias:String(el.Alias||''),base_type:String(el.Type),stereotype:String(el.StereotypeEx||''),
                package_guid:String(Repository.GetPackageByID(el.PackageID).PackageGUID).toUpperCase(),package_path:current.path,parent_guid:parent,
                business_id:(tags.DG_BusinessID||tags.BusinessID||'')=='<memo>'?'':tags.DG_BusinessID||tags.BusinessID||'',opco:(tags.DG_OPCO||tags.OPCO||'')=='<memo>'?'':tags.DG_OPCO||tags.OPCO||'',tags:tags,
                bpmn_references:references,element_tags_hash:tagsHash});
            for(var k=0;k<el.Elements.Count;k++){stack.push(el.Elements.GetAt(k));}
        }
        for(var j=0;j<pkg.Packages.Count;j++){var child=pkg.Packages.GetAt(j);packages.push({pkg:child,parent:String(pkg.PackageGUID).toUpperCase(),path:current.path+' / '+child.Name});}
    }
    for(var id in byId){if(!Object.prototype.hasOwnProperty.call(byId,id)){continue;}var owner=byId[id];
        for(var c=0;c<owner.Connectors.Count;c++){var connector=owner.Connectors.GetAt(c);if(seenConnectors[connector.ConnectorID]){continue;}seenConnectors[connector.ConnectorID]=true;
            try{var record=dgConnector(connector);record.metadata_complete=!!(seenElements[record.source_guid]&&seenElements[record.target_guid]);snapshot.connectors.push(record);}
            catch(e){snapshot.connectors.push({guid:String(connector.ConnectorGUID).toUpperCase(),source_guid:String(Repository.GetElementByID(connector.ClientID).ElementGUID).toUpperCase(),target_guid:String(Repository.GetElementByID(connector.SupplierID).ElementGUID).toUpperCase(),metadata_complete:false,reason:'Connector metadata contract unsupported; inspect in EA.'});}
        }
    }
    Repository.EnsureOutputVisible('Script');Repository.ClearOutput('Script');Session.Output(dgJson(snapshot));
}
main();
