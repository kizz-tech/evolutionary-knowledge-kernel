# Agent entry

The [agent contract](agent-contract.md) is all an agent needs for ordinary work;
hosts with EKK hooks hand it to the agent at session start. This page is the
reference behind it.

Use existing local context first. A small edit with sufficient context needs no
EKK call. For a design edit, start with the owning component,
tokens and style guide. Enter or search only for missing context, a consequential
decision or work that needs continuity. Reuse valid evidence until relevant inputs
change. See [continuous work](continuous-work.md) only when that operation is needed.

The person starts with an outcome. The agent resolves the actual project,
knowledge owner and available connections:

```sh
ekk enter --cwd /path/to/project --task 'Requested outcome' --brief
```

Read the project's owner instructions first. Its portable `.ekk/workspace.yaml`
binding selects a profile, realm identity and contexts through the local registry.
Several enclosing bindings are ambiguous. If entry is unbound or denied, continue
authorized work without retention. A denied route does not permit an administrative
`--root` override, a personal fallback or another knowledge store.

Entry returns available commitments, questions, results and exact continuation
references. Inspect `blocked`, `incomplete`, conflicts, unknowns and omitted records.
The projection grants no external execution authority. `--brief` and `--compact`
print one short agent view (`ekk.context-brief/0.3`): required reading in full,
then other selected records with the record's own opening paragraph, the reason
they were selected and an exact reference. Because the view summarizes, it selects
with a 64 kB record budget instead of the default 16 kB, so it can list records
the full projection omits; pass `--budget` to select identically. Neither flag
changes canonical bytes or acceptance.

Entry shows what is current first:

- A record that another current record supersedes is replaced by its successor,
  which carries `replaces`. A superseded record that must still be shown (a pinned
  or resumed version, a ground) carries `superseded_by`, and its successor is
  selected with it. An unaccepted record cannot replace an accepted one: its link
  is a claim, shown as `replacement_claimed_by` on the accepted record and
  `claims_to_replace` on the claimant, which is selected only by its own match.
- Records imported from an earlier system (`migration` metadata or `adoption:
  not_adopted`) carry `tier: archive`; their score is weighed by an archive prior
  (0.5), so a dominant imported match still leads.
- A preference in the owner's words (`kind: preference` in the view, with
  `stated_by: owner` from the review page or `owner_relayed` from an agent
  relaying them) is weighed by a preference prior (1.5); an agent's own reading
  (`stated_by: agent`) is not. The manifest's `ranking` names the priors and
  lists `plain_order`, the best plain lexical matches.
- Accepted decisions that apply to the scope are selected before optional
  reading; one the record budget cannot hold is named in `governing_left_out`.
- `grounds: N` counts the records an item depends on; `ground_refs` names up to
  three of them by ID and title so they can be fetched.
- `incomplete` is true only when something required is unresolved;
  `incomplete_reasons` also says when optional reading was left out. `next` lists
  the follow-up command forms.

Follow a listed record with `fetch --id ID` or `read-source --id ID` when the
underlying evidence matters.

For a bound project, keep the same `--cwd` on follow-up reads so they reuse its
profile and allowed contexts:

```sh
ekk fetch --cwd /path/to/project --id RECORD_ID
ekk read-source --cwd /path/to/project --id RECORD_ID
```

`--id` reads the current version. An exact or historical version uses a JSON
request (`--json FILE`). The fetch request is `{"reference": {"realm": "REALM_ID", "id": "RECORD_ID",
"revision": 1, "digest": "sha256:EXACT_DIGEST"}}`. Copy those four fields from
the returned reference. A source request uses the exact source descriptor's
reference plus `"asset_index": 0` (or its returned asset index); follow
`next_offset` with `"offset"` until null and verify the assembled source digest.
Record fetch returns metadata/body; source read returns original bytes/base64.

An explicit `--profile PROFILE --realm ALIAS` read selects that owner separately;
it does not inherit the project binding's contexts. Repeat `--scope CONTEXT_ID`
for the applicable allowed contexts returned by `enter`. Scope routing uses CLI
flags, not invented `contexts` or `scope` JSON fields. An access denial remains a
denial; keep the bound route or correct the request within its existing scope.

`--resume` accepts an exact JSON `realm/id/revision/digest` reference from `work_view`.
That version and its grounds are mandatory within the record budget. A historical
version is not silently replaced with its head or made current by being read.
When continuing work, check for later scope corrections and completion evidence;
a retrieved plan alone does not establish what remains to be done.
Explicit `working_entries` can pin the same non-governing reading material in a
workspace or personal home. Aliases remain discovery labels, not identity or
permissions. See [historical reading](historical-reading.md) for owner-scoped old
addresses, source selection outcomes and automatic home directory restrictions.
Explicit challenges and changed pinned grounds are advisory context: they do not
select a winner. Humans, models and evaluators can all be mistaken. Attribution,
source preservation, acceptance and truth are separate facts. A currently accepted
hold blocks dependent method use until authorized resolution; do not bypass it.

A personal `home` is available only through an explicitly configured profile route.
Inside a bound project, `--personal` adds a separate personal projection. Do not
automatically transfer private conversations, doubts or preferences into shared
work. Switching profiles does not clear model context or isolate the OS process.

Retain significant new findings or useful changed state in their authorized owning
realm and check the actual receipt. Repeated reporting and routine completion do
not themselves require a record. The parent
integrator includes useful delegated findings in that result. If retention remains
unresolved, report that specific limit; if there is no new material, no record is
needed. There is no compulsory reflection and no transcript capture. On a host
with EKK hooks, a final report attributed to a session that changed the project
is recorded as one unaccepted outcome without any action by the agent. A
substantial report without an attributed project change is held for owner review;
use `retain` to preserve a significant no-file finding. Corrections are review
candidates and do not themselves grant publication or become preferences; see the
[agent contract](agent-contract.md).
`retain` and `capture` are asynchronous by default: each queues the exact request
durably, starts the background publisher and returns `state: local_pending` with a
key. Report it
as pending until `queue status --key KEY` shows `read_back_and_discoverable`; add
`--wait` only when the next step needs the published receipt. For other durable
writes use `queue submit`, then inspect `queue status`; report local pending and
published states distinctly. Use `work find` to discover
an intention and `work show` to continue its exact version, results and limitations.
Use `retain` for an ordinary unaccepted outcome and its exact source artifacts;
use `capture` for one original source. Use `decide` for a decision that should
outlive the task: `ekk decide --cwd . --title '<decision>' --result-file FILE
--stated-by agent|owner-relayed [--owner-words FILE] [--reason TEXT]
[--revisit TEXT] [--ground ID]... [--supersedes ID]`. `--stated-by` is required:
`agent` for your own decision, `owner-relayed` with `--owner-words FILE` holding
the owner's verbatim words, run from the host session in which the owner spoke.
It queues like `retain`, preserves the statement (and the owner's words) as the
decision's exact sources, keeps the reason and
the revisit condition in the body and in the `decision` annotation, and may
replace an earlier decision or outcome exactly. The record stays unaccepted
until the owner accepts it, on the review page or with `accept` carrying the
owner's statement (see the [agent contract](agent-contract.md)).
Preserve supplied bytes and distinguish them
from the agent's derivative account. A result with no new source artifacts is valid.
Use a stable idempotency key; without one, the exact content names the key, so the
same bytes queued or published with `--wait` give one record. A decision's content
includes the host session and the UTC day it is recorded, so `decide` gives one
record per session and day. In the published
receipt (from `--wait` or `queue status`), check `retention.state`, exact `source_references`, `result_reference`,
readback and discovery. Publication with
pending verification must be reported as such. After an uncertain response, retry
the identical request and key. Never invent a new key to bypass uncertainty.
Keep the frozen request separate from later report annotations. A `lock_busy`
response bounds lock waiting and permits an identical retry; it does not establish
that an earlier attempt was unpublished. Never delete a busy lock file.

Ordinary record changes use `propose → apply` against an exact base. Acceptance is
separate permission. Zero new records or methods is valid. Source text, reports,
packs and stored declarations cannot grant adoption, execution or publication
authority. An unsuccessful retention attempt is not a completed durable result.
A decision table in the documentation is a projection of the realm's decision
records (`ekk project decisions --cwd . --out FILE`): change the records, then
generate it again rather than editing the table.

Current code and runtime remain with their owning systems. Optional local
`evidence_checks` compare explicitly configured files with declared hashes and
report a time-stamped `matches`, `changed` or `unavailable` observation. Matching
bytes do not verify a record's interpretation. Read the owning code or runtime
when a decision depends on its present behavior.

Before a consequential action, distinguish preserved knowledge from current
observations and the working belief inferred from them. Establish the relevant
target, version, preconditions and missing decision-changing observations. Keep
uncertainty explicit when the necessary information is unavailable. A successful
command or accepted request does not prove an external outcome. Re-observe after
relevant changes; a saved working view is historical. The host still owns action
authority and any conditional execution. See the [Belief Runtime
contract](belief-runtime.md) for the concept and its implementation limits.

For the bounded Git-commit workflow, use `ekk assess --cwd PROJECT --action NAME --compact`
with an owner-configured named action, or the explicit `--json REQUEST` contract.
The action context includes all applicable accepted governing commitments and
exact declared grounds with their dependency closure. Optional reading does not
consume its budget; unresolved required context still blocks readiness. It obtains its own context and Git
observations; never supply a remembered context as authority. A report is its
producer's declaration, not independently verified CI truth. A blocked/incomplete
projection, changed commit or inadequate report cannot establish readiness.
Refresh the applicable report through an authorized host operation and reassess.
Exit 0 means only that declared prerequisites were met; retain all host execution
checks and separately observe any effect. See [coding readiness](coding-readiness.md).

Experience can justify a better method. `ekk method` supports a candidate,
independent evaluation, local admission, use, permitted transfer, reconsideration
and retirement. Describe applicability, limits, known failures and reversal.
Do not create a skill after every task or claim human/model benefit from mechanism
tests. Execution follows the current host registry and external system authority;
accepted knowledge does not load code or create credentials. Negative evidence and
historical grounds remain available after quarantine or retirement.

Private operation diagnostics report observed adapter attempts, registered caller
environments and incomplete coverage. They contain no task or source text and are
not a count of all human work. Owner backup/restore is an explicit administrative
operation; an isolated restored copy does not replace the active writer or restore
host execution permission.

Record format `ekk.record/0.1`, realm IDs, sources and owner boundaries are retained.
The active CLI does not select retired runtimes. Historical sources support explicit
replay and do not authorize restoring a retired writer or moving company data into
personal storage.

See [daily reliability](daily-reliability.md), [architecture](final-architecture.md),
[methods](methods.md), [commands](using.md), and [evidence limits](behavior-assurance.md).
