"""A selected real episode can change an artifact; observation is not causality."""
from .work import bounded_text
from .workspace import exact_reference


def improvement(request):
    required={'episode','source','observation','stage','target','change','disposition'}
    if not isinstance(request,dict) or set(request)!=required:raise ValueError('Complete bounded improvement input required')
    for name in ('episode','observation','change'):bounded_text(request[name],name,8000,True)
    if request['source'] not in {'user_feedback','task_log','observed_runtime'}:raise ValueError('Select a real observation source')
    if request['stage'] not in {'retrieved','delivered','used','helpful','unhelpful','unknown'}:raise ValueError('Separate delivery, use and observed helpfulness')
    if request['disposition'] not in {'candidate','implemented','retired','rejected'}:raise ValueError('Unknown improvement disposition')
    target=request['target']
    if not isinstance(target,dict) or set(target)!={'kind','owner','locator'}:raise ValueError('Explicit artifact owner and locator required')
    if target['kind'] not in {'component','tool','check','method','instruction','knowledge','process_removal'}:raise ValueError('Unknown improvement target')
    bounded_text(target['owner'],'owner',2000,True);bounded_text(target['locator'],'locator',2000,True)
    return {'schema':'ekk.improvement/0.1',**request,'claim_source':'recorded observation',
            'causal_effect':'not established','execution_authority':False,
            'verification_owner':target['owner'],'method_admission':'unchanged; use the method lifecycle for adoption'}
