// Deterministic JSON and SHA-256: ES3-compatible, no ActiveX, COM bridge, or network.
function dgJson(v) {
    if (v === null || typeof v == 'undefined') { return 'null'; }
    if (typeof v == 'string') { return '"' + v.replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/[\u0000-\u001f\u2028\u2029]/g,function(c){var shortEsc={'\b':'\\b','\t':'\\t','\n':'\\n','\f':'\\f','\r':'\\r'};return shortEsc[c]||'\\u'+('0000'+c.charCodeAt(0).toString(16)).slice(-4);}) + '"'; }
    if (typeof v == 'number' || typeof v == 'boolean') { return String(v); }
    var out=[], i, keys=[];
    if (v instanceof Array || Object.prototype.toString.call(v)=='[object Array]') {
        for(i=0;i<v.length;i++){out.push(dgJson(v[i]));} return '['+out.join(',')+']';
    }
    for(i in v){if(Object.prototype.hasOwnProperty.call(v,i)){keys.push(i);}} keys.sort();
    for(i=0;i<keys.length;i++){out.push(dgJson(keys[i])+':'+dgJson(v[keys[i]]));} return '{'+out.join(',')+'}';
}
function dgSha256(text) {
    var bytes=unescape(encodeURIComponent(text)), words=[], bitLength=bytes.length*8, i,j;
    for(i=0;i<bytes.length;i++){words[i>>2]=(words[i>>2]||0)|(bytes.charCodeAt(i)<<(24-(i%4)*8));}
    words[bitLength>>5]=(words[bitLength>>5]||0)|(0x80<<(24-bitLength%32));
    words[(((bitLength+64)>>9)<<4)+15]=bitLength;
    var h=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    var k=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
    function r(x,n){return (x>>>n)|(x<<(32-n));}
    for(i=0;i<words.length;i+=16){var w=[],a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],z=h[7];
        for(j=0;j<64;j++){if(j<16){w[j]=words[i+j]|0;}else{var x=w[j-15],y=w[j-2];w[j]=((r(x,7)^r(x,18)^(x>>>3))+w[j-16]+(r(y,17)^r(y,19)^(y>>>10))+w[j-7])|0;}
            var t1=(z+(r(e,6)^r(e,11)^r(e,25))+((e&f)^(~e&g))+k[j]+w[j])|0;
            var t2=((r(a,2)^r(a,13)^r(a,22))+((a&b)^(a&c)^(b&c)))|0;
            z=g;g=f;f=e;e=(d+t1)|0;d=c;c=b;b=a;a=(t1+t2)|0;}
        h[0]=(h[0]+a)|0;h[1]=(h[1]+b)|0;h[2]=(h[2]+c)|0;h[3]=(h[3]+d)|0;
        h[4]=(h[4]+e)|0;h[5]=(h[5]+f)|0;h[6]=(h[6]+g)|0;h[7]=(h[7]+z)|0;}
    var hex='';for(i=0;i<8;i++){hex+=('00000000'+(h[i]>>>0).toString(16)).slice(-8);}return hex;
}
function dgRead(obj,key) { try { var value=obj[key]; return typeof value=='undefined'?null:value; } catch(e){return null;} }
function dgTags(obj) {
    var tags=[], values=obj.TaggedValues;
    if (!values || typeof values.Count=='undefined') { throw new Error('TaggedValues metadata unavailable; cannot verify semantics.'); }
    for(var i=0;i<values.Count;i++){var tag=values.GetAt(i),entry=[String(tag.Name),String(tag.Value)];
        if(String(tag.Value)=='<memo>'){var memo=dgRead(tag,'Notes');if(memo===null){throw new Error('Memo metadata unavailable.');}entry.push(dgSha256(String(memo)));}tags.push(entry);}
    tags.sort(function(a,b){var x=dgJson(a),y=dgJson(b);return x<y?-1:x>y?1:0;}); return tags;
}
function dgEnd(end) {
    if(!end){throw new Error('ConnectorEnd unavailable.');}
    var keys=['Role','Cardinality','Aggregation','Navigable','RoleType','Alias','Qualifier','Containment','Visibility','Derived','Ordering'], out={};
    for(var i=0;i<keys.length;i++){out[keys[i]]=dgRead(end,keys[i]);if(out[keys[i]]===null){throw new Error('ConnectorEnd property unavailable: '+keys[i]);}}
    var note=dgRead(end,'RoleNote');if(note===null){throw new Error('ConnectorEnd RoleNote metadata unavailable.');}out.role_note_hash=dgSha256(String(note));
    return out;
}
function dgConnector(c) {
    var tags=dgTags(c),semantic={},notes=dgRead(c,'Notes');if(notes===null){throw new Error('Connector Notes fingerprint unavailable.');}
    for(var i=0;i<tags.length;i++){if(tags[i][0]=='accessType'){if(typeof semantic.accessType!='undefined'){throw new Error('Ambiguous accessType metadata.');}semantic.accessType=tags[i][1];}}
    return {guid:String(c.ConnectorGUID),id:c.ConnectorID,source_guid:String(Repository.GetElementByID(c.ClientID).ElementGUID).toUpperCase(),target_guid:String(Repository.GetElementByID(c.SupplierID).ElementGUID).toUpperCase(),
        base_type:String(c.Type),stereotype:String(c.StereotypeEx||''),name:String(c.Name||''),direction:String(c.Direction),
        source_role:dgEnd(c.ClientEnd),target_role:dgEnd(c.SupplierEnd),tags_hash:dgSha256(dgJson(tags)),notes_hash:dgSha256(String(notes)),semantic_tags:semantic};
}
