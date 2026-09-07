"""Historical integrity replay, not a causal agent-performance experiment."""
from ekk.semantics import validate, compile_context, reconsider
from ekk import semantics_v1
import json

def record(id, known, valid, sources=None, **extra):
    return {'metadata':{'schema':'ekk/1','id':id,'title':id,'kind':'understanding','scopes':['fixture:api'],'author':'fixture:author','known_from':known,'valid_from':valid,'sources':sources or [],'relations':[],**extra},'body':'Synthetic isolated temporal fixture','path':'fixture/'+id+'.md'}

def main():
    aug='2026-08-01T00:00:00Z';sep='2026-09-05T00:00:00Z'
    records={'notice':record('notice',sep,aug,artifact={'sha256':'0'*64})}
    records['deprecated']=record('deprecated',sep,aug,['notice'])
    validate(records)
    semantics_v1.validate(records)
    before=compile_context(records,['fixture:api'],'','2026-08-20T00:00:00Z','2026-08-20T00:00:00Z')
    after=compile_context(records,['fixture:api'],'','2026-08-20T00:00:00Z','2026-09-06T00:00:00Z')
    assert not before['records'], 'Future knowledge leaked into historical context'
    assert 'deprecated' in [r['id'] for r in after['records']]
    legacy=semantics_v1.compile_context(records,['fixture:api'],'','2026-08-20T00:00:00Z','2026-09-06T00:00:00Z')
    assert legacy['records']==after['records'], 'Existing temporal selection changed'
    assert legacy['compiler']=='0.1.0' and after['compiler']=='0.2.0'
    results={'readers':['0.1.0','0.2.0'],'legacy_temporal_selection_preserved':True,'schema':'ekk.functional-replay/1','checks':{'not_known_in_august':True,'retrospectively_applicable_in_august':True,'no_automatic_obligation':not any(r['governs'] for r in after['records']),'no_automatic_evolution_task':not reconsider(records,['fixture:api'],sep,sep)['candidates']},'proof_limit':'Synthetic functional integrity replay only; no model, longitudinal experiment or scientific benefit measured.'}
    print(json.dumps(results,indent=2))

if __name__=='__main__':main()
