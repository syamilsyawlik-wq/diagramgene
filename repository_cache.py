"""Small private cache of derived catalogues, never copies of QEA files."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from catalogue_snapshot import normalise_snapshot

CACHE_VERSION=1
CACHE_PATH=Path(__file__).resolve().parent/'.diagramgene'/'catalogue-cache'
MAX_CACHE_BYTES=64*1024*1024


class CatalogueCache:
    def __init__(self,path=CACHE_PATH): self.path=Path(path)

    def key(self,fingerprint,scope):
        return hashlib.sha256(json.dumps([CACHE_VERSION,fingerprint,int(scope)]).encode()).hexdigest()

    def load(self,source,scope):
        target=self.path/(self.key(source['fingerprint'],scope)+'.catalogue.json')
        try:
            if target.stat().st_size>MAX_CACHE_BYTES: return None
            envelope=json.loads(target.read_text(encoding='utf-8'))
            payload=envelope['catalogue']
            encoded=json.dumps(payload,sort_keys=True,separators=(',',':')).encode()
            provenance=payload['repository_source']
            if (envelope['version']!=CACHE_VERSION or envelope['digest']!=hashlib.sha256(encoded).hexdigest()
                or provenance['fingerprint']!=source['fingerprint'] or provenance['backend_path']!=source['path']
                or envelope['scope']!=int(scope)): return None
            return normalise_snapshot(payload,trusted_local=True)
        except (OSError,ValueError,TypeError,KeyError): return None

    def save(self,source,scope,catalogue):
        self.path.mkdir(mode=0o700,parents=True,exist_ok=True)
        encoded=json.dumps(catalogue,sort_keys=True,separators=(',',':')).encode()
        envelope={'version':CACHE_VERSION,'scope':int(scope),'digest':hashlib.sha256(encoded).hexdigest(),'catalogue':catalogue}
        output=json.dumps(envelope,ensure_ascii=False).encode()
        if len(output)>MAX_CACHE_BYTES: return False
        target=self.path/(self.key(source['fingerprint'],scope)+'.catalogue.json')
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path,suffix='.tmp',delete=False) as stream:
                temporary=Path(stream.name);os.chmod(stream.name,0o600);stream.write(output)
            temporary.replace(target);temporary=None
            # Bound cache storage without touching any source repositories.
            for old in sorted(self.path.glob('*.catalogue.json'),key=lambda p:p.stat().st_mtime_ns,reverse=True)[8:]: old.unlink()
            return True
        finally:
            if temporary and temporary.exists(): temporary.unlink()
