"""Reproducible synthetic benchmark, no customer database or generated cache in Git.

Run: .venv/bin/python tests/benchmark_qea.py --objects 20000
Numbers are observed, not an EA-version or production performance guarantee.
"""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import sys
import tempfile
import time
import tracemalloc

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from qea_fixture import make_qea
from repository_cache import CatalogueCache
from repository_providers import LocalQEARepositoryProvider


def measure(operation):
    gc.collect();tracemalloc.start();start=time.perf_counter()
    result=operation()
    seconds=time.perf_counter()-start;_current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    return result,{'seconds':round(seconds,4),'python_peak_mib':round(peak/1048576,2)}


def benchmark(objects=20000):
    with tempfile.TemporaryDirectory() as temp:
        path=make_qea(Path(temp)/'synthetic.qea',large=objects)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        provider=LocalQEARepositoryProvider(path,cache=CatalogueCache(Path(temp)/'derived'))
        overview,scan=measure(provider.overview)
        _page,browse=measure(lambda:provider.page('elements',2,limit=50))
        catalogue,extract=measure(lambda:provider.catalogue(2,element_limit=objects+2,connector_limit=objects+1))
        total=len(catalogue['elements']);del catalogue
        _cached,cached=measure(lambda:provider.catalogue(2))
        assert provider.last_cache_hit and total==objects+2
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
        return {'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'platform':platform.platform(),
            'database_mib':round(path.stat().st_size/1048576,2),'counts':overview['counts'],
            'overview':scan,'browse_50':browse,'catalogue_extraction_and_cache_write':extract,'cache_load':cached,
            'cache_hit':provider.last_cache_hit,'database_sha256_unchanged':True,
            'measurement':'tracemalloc peak per operation; excludes SQLite native heap, fixture construction and process RSS. Cache load still validates normalized metadata.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--objects',type=int,default=20000)
    print(json.dumps(benchmark(parser.parse_args().objects),indent=2))
