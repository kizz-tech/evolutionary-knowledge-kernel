"""Synthetic end-to-end proof. Never opens global knowledge or company data."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
from dataclasses import asdict
import argparse
import json
import time
from .realms import RealmStore,Grant,RecordRef,PermissionDenied
from .federation import Federation,digest as text_digest
from .capabilities import (CapabilityRuntime,CapabilityManifest,BasisRef,CapabilityError,
                          BOUNDARY_CHECK,verify_boundary_check,run_boundary_check,materialize)
from .experiments import deterministic_rehearsal
from .realm_registry import RealmRegistry


def run(destination):
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Pilot requires a new output directory')
    destination.mkdir(parents=True)
    owner=Grant('owner',('*',),audiences=('*',))
    employee=Grant('employee',('read','contribute','reference'),scopes=('fixture:project',),audiences=('team',),destinations=('fixture:personal',),disclosure_audiences=('private',))
    personal=RealmStore.create(destination/'personal','fixture:personal',grants=[owner])
    organization=RealmStore.create(destination/'organization','fixture:organization',grants=[owner,employee])
    public=RealmStore.create(destination/'public-candidate','fixture:public',grants=[owner])
    person,org,target=personal.session('owner'),organization.session('owner'),public.session('owner')
    worker=organization.session('employee');scopes=['fixture:project']
    private=person.contribute('Synthetic personal interpretation, never a company standard.',scopes=scopes)
    proposal=worker.contribute('A transfer requires source disclosure, destination acceptance and exact byte verification.',scopes=scopes,audience='team')
    blocked=False
    try:worker.adopt(proposal,predicate='transfer-standard',affected_scopes=scopes,expected_current=[])
    except PermissionDenied:blocked=True
    assert blocked
    org.adopt(proposal,predicate='transfer-standard',affected_scopes=scopes,expected_current=[],basis='Synthetic owner review of contributor proposal')
    start=time.perf_counter();context=worker.view(scopes=scopes,purpose='Prepare an internal tool').compile();compile_seconds=time.perf_counter()-start
    assert any(r['governing'] for r in context['records'])
    federation=Federation(destination/'private-transfer-receipts')
    federation.prepare('reference','reference',worker,person,proposal,scopes=scopes)
    federation.accept('reference',worker,person)
    reference=federation.resolve('reference',worker,person)
    federation.prepare('projection','projection',worker,person,proposal,scopes=scopes,expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
    federation.accept('projection',worker,person)
    projection=federation.resolve('projection',worker,person)
    federation.prepare('import','import',org,person,proposal,scopes=scopes)
    imported=federation.accept('import',org,person)
    assert federation.accept('import',org,person)==imported
    assert person.view(scopes=scopes).get(RecordRef.from_dict(imported['ref']))['governing'] is False
    clean='Synthetic reference example: review a contribution, explicitly adopt it, then verify a reusable capability.'
    federation.prepare('derive','derive',org,target,proposal,scopes=['fixture:public'],audience='public',body=clean,approved_digest=text_digest(clean))
    derived=federation.accept('derive',org,target)
    public_record=target.view(scopes=['fixture:public']).get(RecordRef.from_dict(derived['ref']))
    assert proposal.record_id not in json.dumps(public_record)
    artifact=destination/'boundary-check.json';artifact_digest=materialize(artifact,BOUNDARY_CHECK)
    manifest=CapabilityManifest('boundary-check','1','fixture:code-owner','fixture:boundary-check/1',artifact_digest,
        (BasisRef(proposal.realm_id,proposal.record_id,proposal.digest),),'fixture-materializer/1','synthetic-only',(),
        'fixed-boundary-verifier/1','Re-admit the same checked bytes','Basis changed, permission withdrawn or verifier failed',True)
    def admitted(operation,descriptor):
        org.authorize(operation,ref=proposal)
        return True
    def current(basis):
        try:return org.view(scopes=scopes).get(RecordRef(basis.realm_id,basis.record_id,basis.revision_digest))['governing'] is True
        except (PermissionDenied,OSError):return False
    runtime=CapabilityRuntime(admit=admitted,basis_is_current=current,verifier=verify_boundary_check,runner=run_boundary_check,
                              retirement_verifier=lambda m,reason:run_boundary_check(BOUNDARY_CHECK,{'source_disclosure':True,'target_acceptance':False,'digest_match':True})['passed'] is False)
    inert=False
    try:runtime.run('boundary-check','1',{})
    except CapabilityError:inert=True
    assert inert
    runtime.activate(manifest,artifact.read_bytes())
    reuse=[runtime.run('boundary-check','1',fixture) for fixture in (
        {'source_disclosure':True,'target_acceptance':True,'digest_match':True},
        {'source_disclosure':True,'target_acceptance':False,'digest_match':True})]
    assert reuse[0]['passed'] and not reuse[1]['passed']
    outcome=org.contribute('Synthetic repeated use: valid transfer passed; missing acceptance rejected. No model benefit measured.',scopes=scopes,audience='team',kind='outcome',relations=[{'predicate':'about','target':proposal.to_dict()}])
    revised=org.contribute('Same transfer requirements; record explicit review purpose.',scopes=scopes,audience='team')
    org.adopt(revised,predicate='transfer-standard',affected_scopes=scopes,expected_current=[proposal],relations=[{'predicate':'supersedes','target':proposal.to_dict(),'within_scopes':scopes}])
    candidates=runtime.reconsider();assert candidates
    runtime.retire('boundary-check','1',reason='Synthetic pilot closes; fixed replacement checker passes negative holdout',replacement_verified=True)
    org.replace_policy([owner],expected_epoch=1)
    revoked=False
    try:federation.resolve('projection',worker,person,known_at='2026-01-01T00:00:00Z')
    except PermissionDenied:revoked=True
    assert revoked
    registry=RealmRegistry(destination/'registry.yaml');registry.initialize('owner')
    for root in ('personal','organization','public-candidate'):registry.register(destination/root)
    project=destination/'project';project.mkdir();registry.bind(project,'fixture:organization',scopes)
    result={'schema':'ekk.synthetic-pilot/1','status':'passed','real_data_used':False,'scientific_proven':False,
            'checks':{'controlled_adoption':blocked,'four_operations':True,'idempotent_import':True,'import_not_adopted':True,
                      'public_lineage_minimized':True,'descriptor_inert':inert,'verified_reuse':True,'basis_reconsideration':bool(candidates),
                      'projection_revocation':revoked,'global_router':registry.enter(project)['runtime']=='governed/3'},
            'capability_outcomes':reuse,'capability_history':runtime.history,'manifest':manifest.descriptor(),
            'context_snapshot':context['snapshot_hash'],'compile_seconds':compile_seconds,
            'reconsideration':candidates,'outcome_ref':outcome.to_dict(),
            'limits':'Synthetic local trusted adapter proof; no corporate IAM, external publication or model experiment.'}
    (destination/'result.json').write_text(json.dumps(result,indent=2))
    (destination/'measurement-rehearsal.json').write_text(json.dumps(deterministic_rehearsal(),indent=2))
    (destination/'README.md').write_text('# Synthetic EKK pilot\n\nAll data are artificial. Runtime checks passed; no scientific hypothesis is proven.\n\n'+
        '\n'.join(f'- {name}: {value}' for name,value in result['checks'].items())+'\n\nSee result.json and measurement-rehearsal.json for machine-readable verification evidence.\n')
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(prog='ekk pilot');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        result=run(args.output);print(json.dumps({'status':result['status'],'output':str(args.output.resolve()),'checks':result['checks'],'scientific_proven':False},indent=2));return 0
    except (ValueError,OSError) as exc:
        parser.exit(2,f'ekk pilot: {exc}\n')

if __name__=='__main__':raise SystemExit(main())
