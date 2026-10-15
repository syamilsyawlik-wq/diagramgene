"""Non-secret target profiles. Live EA identity must still be verified by JScript."""
import json
from pathlib import Path
from ea_catalogue import guid

PROFILE_PATH = Path(__file__).resolve().parent / '.diagramgene' / 'profiles.json'


def boolean_option(values, key, default=False):
    value=values.get(key,default)
    if type(value) is not bool: raise ValueError(key+' harus boolean true/false, bukan string.')
    return value


def validate_identity(identity):
    if not isinstance(identity, dict):
        raise ValueError('Expected repository identity belum diisi.')
    kind = identity.get('kind')
    keys = ('kind', 'locator') if kind == 'local' else ('kind', 'server', 'database', 'provider')
    if kind not in ('local', 'server') or set(identity) != set(keys):
        raise ValueError('Identity hanya boleh memuat locator lokal atau server/database/provider non-rahasia.')
    if any(not isinstance(identity[k], str) or not identity[k].strip() for k in keys):
        raise ValueError('Repository identity tidak lengkap.')
    if kind == 'local' and not identity['locator'].lower().endswith(('.qea', '.qeax')):
        raise ValueError('Profile lokal membutuhkan locator .qea/.qeax dari exporter EA.')
    if any(any(word in identity[k].lower() for word in ('password=', 'pwd=', 'user id=', 'uid=', '://', '@')) for k in keys if k != 'kind'):
        raise ValueError('Jangan menyimpan credentials, URL, atau connection string pada profile.')
    return {k: identity[k] for k in keys}


def normalise_profile(profile):
    profile = dict(profile or {})
    environment = profile.get('environment', 'local')
    if environment not in ('local', 'production'):
        raise ValueError('Environment repository tidak dikenal.')
    identity = validate_identity(profile['expected_identity']) if profile.get('expected_identity') else None
    if environment == 'production' and identity and identity['kind'] != 'server':
        raise ValueError('Holding Production harus memverifikasi identity server, bukan clone lokal.')
    if environment == 'local' and identity and identity['kind'] != 'local':
        raise ValueError('Local Testing hanya untuk .qea/.qeax lokal; repository server wajib memakai Holding Production.')
    result = {'name': str(profile.get('name', 'Local Testing' if environment == 'local' else 'Holding Production')),
              'environment': environment, 'expected_identity': identity,
              'catalogue_root_guid': guid(profile['catalogue_root_guid']) if profile.get('catalogue_root_guid') else '',
              'scope_package_guid': guid(profile['scope_package_guid']) if profile.get('scope_package_guid') else '',
              'output_package_guid': guid(profile['output_package_guid']) if profile.get('output_package_guid') else '',
              'opco': str(profile.get('opco', '')).strip(),
              'last_snapshot_at': str(profile.get('last_snapshot_at', '')),
              'allow_new_elements': boolean_option(profile,'allow_new_elements',environment=='local')}
    return result


def load_profiles(path=PROFILE_PATH):
    path = Path(path)
    if not path.exists():
        return {name: normalise_profile({'name': name, 'environment': env})
                for name, env in [('Local Testing', 'local'), ('Holding Production', 'production')]}
    raw = json.loads(path.read_text(encoding='utf-8'))
    if raw.get('schema_version') != 1 or not isinstance(raw.get('profiles'), dict):
        raise ValueError('Schema profile tidak didukung.')
    return {name: normalise_profile(p) for name, p in raw['profiles'].items()}


def save_profiles(profiles, path=PROFILE_PATH):
    # Whitelist fields; never serialize an arbitrary dict containing credentials.
    values = {name: normalise_profile(p) for name, p in profiles.items()}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'schema_version': 1, 'profiles': values}, indent=2), encoding='utf-8')
    temporary.replace(path)
