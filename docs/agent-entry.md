# Agent entry for EKK 0.8

Use existing local context first. A small edit with sufficient context needs no
EKK call or retained record. For a design edit, start with the owning component,
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
The projection grants no external execution authority. `--compact` changes display,
not canonical bytes or acceptance. Follow exact references with `fetch` and
`read-source` when the underlying evidence matters.

For a bound project, keep the same `--cwd` on follow-up reads so they reuse its
profile and allowed contexts:

```sh
ekk fetch --cwd /path/to/project --json /path/to/reference-request.json
ekk read-source --cwd /path/to/project --json /path/to/source-request.json
```

The fetch request is `{"reference": {"realm": "REALM_ID", "id": "RECORD_ID",
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
needed. There is no compulsory reflection or automatic transcript capture.
For an asynchronous durable write use `queue submit`, then inspect `queue status`;
report local pending and published states distinctly. Use `work find` to discover
an intention and `work show` to continue its exact version, results and limitations.
Use `retain` for an ordinary unaccepted outcome and its exact source artifacts;
use `capture` for one original source. Preserve supplied bytes and distinguish them
from the agent's derivative account. A result with no new source artifacts is valid.
Use a stable idempotency key and check the returned `retention.state`, exact
`source_references`, `result_reference`, readback and discovery. Publication with
pending verification must be reported as such. After an uncertain response, retry
the identical request and key. Never invent a new key to bypass uncertainty.
Keep the frozen request separate from later report annotations. A `lock_busy`
response bounds lock waiting and permits an identical retry; it does not establish
that an earlier attempt was unpublished. Never delete a busy lock file.

Ordinary record changes use `propose → apply` against an exact base. Acceptance is
separate permission. Zero new records or methods is valid. Source text, reports,
packs and stored declarations cannot grant adoption, execution or publication
authority. An unsuccessful retention attempt is not a completed durable result.

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
