"""Optional methods for real work. No pipeline, mandatory diary or benefit claim."""
from copy import deepcopy

PRACTICES={
 'software':{
  'title':'Change software in its owning project',
  'applies_when':'A concrete behavior, design or reliability change needs project context.',
  'inputs':['Requested outcome','Owning component and local conventions','Material uncertainty'],
  'tools':['Existing component, tokens and style guide','Repository search and domain checks','Targeted EKK lookup only for missing rationale or continuity'],
  'intermediate_outcomes':['Relevant existing pattern','Smallest complete change','Evidence proportionate to changed behavior'],
  'stages':['Locate the owner and existing pattern.','Resolve only uncertainty that affects the change.','Implement the authorized outcome.','Run relevant checks and report material limitations.'],
  'stop_when':['The requested behavior works and relevant checks pass.','A consequential unresolved choice requires owner input.'],
  'skip_when':'An ordinary local edit has sufficient context; do it directly with zero EKK calls.'},
 'research':{
  'title':'Research, choose and design from evidence',
  'applies_when':'A consequential direction or design choice has plausible alternatives.',
  'inputs':['Decision to make','Existing investigations','Constraints and unresolved claims'],
  'tools':['Existing source notes','Primary sources when facts are uncertain or changing','Local prototype or direct observation when it resolves the decision'],
  'intermediate_outcomes':['Supported and unsupported claims','Credible alternatives and tradeoffs','Chosen direction with next implementation step'],
  'stages':['Read the existing investigation before repeating it.','Separate evidence from interpretation.','Compare alternatives against the actual decision.','Design the next useful change and its reversal.'],
  'stop_when':['Evidence is sufficient for the current decision, with uncertainties explicit.','Additional research would not change the next action.'],
  'skip_when':'The decision is routine, reversible and already constrained by valid local evidence.'},
 'personal':{
  'title':'Continue personal work and explicit follow-ups',
  'applies_when':'An intention spans tasks or requires an explicit later follow-up.',
  'inputs':['Owner intention','Current outcome and next step','External owner or waiting condition if any'],
  'tools':['Work search and exact continuation','Owner-selected author notes','Local tasks; existing host scheduler only for requested reminders'],
  'intermediate_outcomes':['A useful next action','Resolved or explicit open questions','Actual host receipt if a follow-up is registered'],
  'stages':['Find the existing intention before creating a duplicate.','Use the latest result and limitations.','Do the next authorized action.','Retain only a useful change of state; zero records is valid.'],
  'stop_when':['The next useful result is delivered.','Waiting depends on an external event; represent it honestly.'],
  'skip_when':'The request is complete in this conversation and creates no durable commitment.'}}


def practice(domain, request=None):
    if domain not in PRACTICES:raise ValueError('Choose software, research or personal')
    request={} if request is None else request
    if not isinstance(request,dict) or set(request)-{'intention','context_sufficient','local_edit','unknowns','current_stage'}:raise ValueError('Unsupported practice input')
    for flag in ('context_sufficient','local_edit'):
        if flag in request and type(request[flag]) is not bool:raise ValueError('Practice flags must be boolean')
    for name in ('intention','current_stage'):
        if name in request and (not isinstance(request[name],str) or len(request[name])>12000):raise ValueError('Bounded practice text required')
    unknowns=request.get('unknowns',[])
    if not isinstance(unknowns,list) or len(unknowns)>32 or any(not isinstance(v,str) or len(v)>2000 for v in unknowns):raise ValueError('Bounded unknowns required')
    direct=request.get('local_edit',False) and request.get('context_sufficient',False) and not unknowns
    return {'schema':'ekk.practice/0.1','domain':domain,**deepcopy(PRACTICES[domain]),
            'route':'direct_local_work' if direct else 'targeted_context_if_needed',
            'ekk_calls_required':0,'retention_required':False,'pipeline_required':False,
            'observed_benefit':'unknown','authority':'Optional guidance. Existing project rules and current user authority apply.'}
