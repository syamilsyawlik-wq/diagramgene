"""Fail-closed guard for legacy TRM; production integration is explicitly deferred."""
import json
from pathlib import Path
from repository_profiles import normalise_profile


def wrap_local_generator(script, profile=None, mode='VALIDATE_ONLY', approved=False):
    profile=normalise_profile(profile)
    if type(approved) is not bool: raise ValueError('approved harus boolean.')
    root=Path(__file__).resolve().parent
    guard=(root/'runtime/metadata.js').read_text()+'\n'+(root/'runtime/repository_identity.js').read_text()
    data=json.dumps({'profile':profile,'mode':mode,'approved':bool(approved)},ensure_ascii=True)
    return guard+'\nvar LEGACY_POLICY = '+data+r''';
function dgLegacyRun(){
 var actual=dgIdentity(Repository);
 if(!LEGACY_POLICY.profile.expected_identity||dgJson(actual)!=dgJson(LEGACY_POLICY.profile.expected_identity)){throw new Error('Repository identity mismatch/unverified.');}
 if(actual.kind!='local'||LEGACY_POLICY.profile.environment!='local'){throw new Error('TRM shared catalogue integration pending: production writes are blocked.');}
 if(LEGACY_POLICY.mode=='VALIDATE_ONLY'){Session.Output('VALIDATE_ONLY: legacy TRM generation is local-only; no model writes. Relationship-aware TRM preflight is P1.');return;}
 if(LEGACY_POLICY.mode!='EXECUTE'||!LEGACY_POLICY.approved){throw new Error('Local TRM EXECUTE requires explicit approval.');}
 __SCRIPT__
}
dgLegacyRun();
'''.replace('__SCRIPT__',script)
