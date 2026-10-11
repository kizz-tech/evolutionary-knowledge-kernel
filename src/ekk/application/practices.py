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


# Phases are optional decisions within any domain, not a required sequence.
# Keep PRACTICES unchanged: its exact bytes identify existing method artifacts.
PHASES={
 'research':{
  'decision':'What information would change the current question or next action?',
  'output':'Supported findings, unresolved claims and the next useful decision.',
  'experience_use':['Check relevant prior investigations and their exact grounds.',
                    'Recheck changed conditions; use real materials for the present question.'],
  'evidence':['Source provenance and currency','Direct observations separated from interpretation'],
  'stop_when':['Evidence suffices for the current decision, with uncertainty explicit.',
               'Further research would not change the next action.']},
 'design':{
  'decision':'Which design delivers the required ability within current constraints?',
  'output':'A usable target, credible alternatives, tradeoffs and material limits.',
  'experience_use':['Use earlier successes, friction and counterexamples when conditions still apply.',
                    'Check how the user will reach and use the result, not only its internal mechanism.'],
  'evidence':['Required user ability and actual entry point','Grounds for alternatives and constraints'],
  'stop_when':['The target and its limits are clear enough to implement or choose.',
               'A consequential unresolved choice needs owner input.']},
 'planning':{
  'decision':'What is the next complete authorized step from the actual current state?',
  'output':'The next useful step, dependencies, scope and completion or stopping conditions.',
  'experience_use':['Read actual completion receipts before treating old plans as unfinished work.',
                    'Use prior delays and recovery outcomes to identify applicable dependencies.'],
  'evidence':['Current scope and authority','Verified completed work and unresolved dependencies'],
  'stop_when':['The next step is actionable and proportionate to the task.',
               'An external dependency or missing authority prevents the next action.']},
 'implementation':{
  'decision':'Does the authorized result work through its real entry point?',
  'output':'A completed usable flow, observed result and explicit residual unknowns.',
  'experience_use':['Apply relevant prior lessons and preserve critical successful behavior.',
                    'Identify the changed decision and the actual result in the ordinary final report.'],
  'evidence':['Observed result through the actual user flow','Mechanism checks reported separately from real use',
              'Exact grounds for a reused lesson and remaining unknowns'],
  'stop_when':['The requested flow is delivered with applicable checks and material limits reported.',
               'A real blocker requires owner input or an external change.']}}


def practice(domain, request=None, *, phase=None):
    if domain not in PRACTICES:raise ValueError('Choose software, research or personal')
    if phase is not None and phase not in PHASES:raise ValueError('Choose research, design, planning or implementation')
    request={} if request is None else request
    if not isinstance(request,dict) or set(request)-{'intention','context_sufficient','local_edit','unknowns','current_stage'}:raise ValueError('Unsupported practice input')
    for flag in ('context_sufficient','local_edit'):
        if flag in request and type(request[flag]) is not bool:raise ValueError('Practice flags must be boolean')
    for name in ('intention','current_stage'):
        if name in request and (not isinstance(request[name],str) or len(request[name])>12000):raise ValueError('Bounded practice text required')
    unknowns=request.get('unknowns',[])
    if not isinstance(unknowns,list) or len(unknowns)>32 or any(not isinstance(v,str) or len(v)>2000 for v in unknowns):raise ValueError('Bounded unknowns required')
    direct=request.get('local_edit',False) and request.get('context_sufficient',False) and not unknowns
    result={'schema':'ekk.practice/0.1','domain':domain,**deepcopy(PRACTICES[domain]),
            'route':'direct_local_work' if direct else 'targeted_context_if_needed',
            'ekk_calls_required':0,'retention_required':False,'pipeline_required':False,
            'observed_benefit':'unknown','authority':'Optional guidance. Existing project rules and current user authority apply.'}
    if phase is not None:
        result.update(phase=phase,phase_guidance=deepcopy(PHASES[phase]))
    return result
