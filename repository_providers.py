"""Local and JSON providers share the existing normalized catalogue contract.

There is deliberately no PCS/production database provider.
"""
from pathlib import Path
from typing import Protocol

from catalogue_snapshot import read_snapshot
from qea_reader import QEAReader, QEAError, probe
from qea_catalogue_adapter import adapt
from repository_cache import CatalogueCache


class RepositoryProvider(Protocol):
    def catalogue(self,package_id=None,force=False): ...


class JSONSnapshotRepositoryProvider:
    def __init__(self,raw): self.snapshot=read_snapshot(raw)
    def catalogue(self,package_id=None,force=False): return self.snapshot


class LocalQEARepositoryProvider:
    def __init__(self,path,allowed_root=None,cache=None,expected_fingerprint=None):
        self.path=path;self.allowed_root=allowed_root;self.cache=cache if cache is not None else CatalogueCache()
        self.expected_fingerprint=expected_fingerprint;self.last_cache_hit=False

    def current(self):
        source=probe(self.path,self.allowed_root)
        if self.expected_fingerprint and source['fingerprint']!=self.expected_fingerprint:
            raise QEAError('Repository berubah sejak analisis. Tekan Segarkan repository dan review ulang rencana.')
        return source

    def overview(self):
        self.current()
        with QEAReader(self.path,self.allowed_root).read() as reader: return reader.overview()

    def packages(self,**filters):
        self.current()
        with QEAReader(self.path,self.allowed_root).read() as reader: return reader.packages(**filters)

    def page(self,section,package_id,**filters):
        self.current()
        with QEAReader(self.path,self.allowed_root).read() as reader: return reader.page(section,package_id,**filters)

    def catalogue(self,package_id=None,force=False,element_limit=10000,connector_limit=25000):
        if package_id is None: raise QEAError('Pilih package katalog terlebih dahulu.')
        source=self.current();self.last_cache_hit=False
        if not force:
            cached=self.cache.load(source,package_id)
            if cached is not None:
                self.last_cache_hit=True;return cached
        try:
            with QEAReader(self.path,self.allowed_root).read() as reader:
                raw=reader.extract(package_id,element_limit,connector_limit)
            result=adapt(raw)
            if self.current()['fingerprint']!=source['fingerprint']:
                raise QEAError('Repository berubah setelah capture; hasil dibatalkan.')
            self.cache.save(source,package_id,result)
            return result
        except QEAError: raise
        except (ValueError,KeyError,TypeError,RecursionError) as exc:
            raise QEAError('Metadata QEA tidak konsisten/belum didukung: '+str(exc)) from exc
