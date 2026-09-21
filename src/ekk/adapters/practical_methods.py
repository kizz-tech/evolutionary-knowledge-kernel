"""Registered read-only practical adapters, using the established method lifecycle."""
import json
from ..application.practices import PRACTICES, practice
from ..model.methods import sha
from .method_execution import MethodAdapter


def artifact(domain):
    return (json.dumps({'schema':'ekk.practice-artifact/0.1','domain':domain,'guide':PRACTICES[domain]},sort_keys=True)+'\n').encode()


def registry():
    result={}
    for domain in PRACTICES:
        raw=artifact(domain)
        cases={'proportionate-local':{'input':{'intention':'A real local edit already has sufficient context.',
                    'context_sufficient':True,'local_edit':True}},
               'unresolved-context':{'input':{'intention':'A consequential next step.', 'unknowns':['Existing owner decision']}}}
        def evaluate(output,case):
            direct=case['input'].get('local_edit',False)
            return (output.get('route')==('direct_local_work' if direct else 'targeted_context_if_needed')
                    and output.get('retention_required') is False and output.get('observed_benefit')=='unknown')
        result['builtin:'+domain+'-work']=MethodAdapter('builtin:'+domain+'-work','1','practice-contract/1',(),
            lambda value,expected=raw:value==expected,
            lambda value,request,selected=domain:practice(selected,request),cases,evaluate)
    return result


def spec(domain):
    return {'schema':'ekk.method/0.1','adapter':'builtin:'+domain+'-work','adapter_version':'1',
            'artifact_digest':sha(artifact(domain)),'applicability':{'task_family':[domain],
                'environment':['owner-local'],'model':['*']},'privileges':[],
            'rollback':'Stop using the optional guide; quarantine or retire its local admission.',
            'reconsider_when':['Actual use reveals friction or a conflicting project convention.'],
            'limitations':['Read-only planning guidance; does not perform or authorize project actions.',
                'Contract checks verify routing and boundaries, not usefulness or improved agent quality.']}
