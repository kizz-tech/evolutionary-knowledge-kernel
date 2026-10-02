# Evolutionary Knowledge Kernel

**A personal way into work, shared continuity, and methods that can improve with experience.**

The 0.8 and 0.9 increments add proportionate entry, discoverable intentions,
versioned continuation, a durable publication queue, read-only author notes,
explicit local follow-ups and experience recorded from the host's own events. Start with [continuous work](docs/continuous-work.md). A local
edit with sufficient context needs no EKK call and no new record. Practical
software, research and personal-work guidance is optional; usefulness is assessed
through ordinary work, feedback and selected logs.

[Release 0.9.1](docs/release-notes-0.9.1.md) (on [0.9.0](docs/release-notes-0.9.0.md)) records experience from the host's
own events (a session's final report, the owner's corrections), shows current
knowledge first, delivers one [agent contract](docs/agent-contract.md) at session
start and measures itself through the owner's weekly review. It implements the
[1.0 release package](docs/releases/README.md); consult its
[status](docs/releases/1.0/status.md) for delivered and measured coverage, since a
specification is not a delivery claim.

Start from an intention: investigate a question, continue a change, or prepare a
handoff. EKK returns authorized context, accepted commitments, results, questions
and exact continuation references. Personal drafts stay with their owner; shared
work can continue when its participants or agents change.

The research focus is whether useful ways of working can **persist, transfer and
be revised or retired**. More stored text is not itself an improvement. An
accepted record is not an execution permit or proof that a person understands it.

The evolving [concept](docs/concept.md) connects that experience to the next
action: distinguish the world, observations, working beliefs and commitments;
identify decision-relevant unknowns; and observe outcomes separately from command
success. The [Belief Runtime contract](docs/belief-runtime.md) defines a temporary
working projection and its boundary with host-owned sensors and capabilities.
A bounded Python projection and the [manual coding workflow](docs/coding-readiness.md)
implement the first slice. `ekk assess` observes the selected Git commit and
configured reports through the ordinary bound CLI route. Automatic host execution
is not included; empirical benefit remains to be established.

Our [open research agenda](research/agenda.md) asks **when past work makes future
work better**: what makes capabilities transferable, how to repair consequences
of mistaken knowledge, and how to evaluate improvement as a system adapts. The
[roadmap](ROADMAP.md) connects nine open questions to concrete next tasks, evidence
gates and [ways to contribute](CONTRIBUTING.md).

## Try the complete method cycle

From this checkout, with Python 3.11+ and Git:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python examples/method_transfer.py
```

The disposable example uses two synthetic participants, private exploration and
shared work. It evaluates a harmless handoff method, restores it in a fresh
process, transfers exact authorized bytes, evaluates and admits it locally,
observes an adverse case, quarantines and retires the old version, and verifies
its replacement. It makes no model calls and sends nothing externally.

For an existing authorized project:

```sh
ekk enter --cwd /path/to/project --task 'Continue the investigation' --compact
```

[Quickstart](docs/quickstart.md) explains personal home, explicit personal context,
exact resume, and the CLI. [Method lifecycle](docs/methods.md) shows the public
operations and their boundaries.

## What the parts do

| Part | Responsibility | Owning state |
| --- | --- | --- |
| Personal entry | Start from intent, read private drafts, continue exact prior work | Explicit personal route and owner-held records |
| Shared continuity | Preserve accepted results, commitments, grounds and continuation anchors | Project realm, Git and other owning systems |
| Revisable methods | Evaluate, admit, use, transfer, reconsider and retire an exact method | Ordinary records and receipts; host-owned execution evidence |
| Action readiness | Assess configured check reports for a selected Git commit | Temporary experimental projection and read-only CLI adapter; host-owned authority |

The local kernel retains stable IDs, exact source bytes, versions, provenance,
controlled writes and acceptance receipts. The record format remains **0.1**.
Runtime **0.9.1** has one active CLI; old runtimes are explicit historical replay
artifacts outside the installed package. No company data is moved into personal
storage by entry or this migration.

The installed method adapter is deliberately small and read-only. EKK does not
rebuild identity management, a task tracker or universal approvals. External
execution, credentials, permissions and publication remain with their owning
systems. Profiles select routes within a trusted local process; they are not an
OS sandbox.

[Daily reliability](docs/daily-reliability.md) covers result retention with exact
read-back, private diagnostics, owner backup/restore, explicit challenges and
current repository evidence. [Release 0.7](docs/release-notes-0.7.md) includes that
increment and the Belief Runtime preview; [0.8](docs/release-notes-0.8.md) adds
continuous work and [0.8.4](docs/release-notes-0.8.4.md) writes that finish. Human and AI statements remain fallible; acceptance and
execution authority follow current ownership and grants.

## Evidence and research

Run the installed coding workflow in a disposable Git repository:

```sh
.venv/bin/python examples/coding_readiness.py --ekk .venv/bin/ekk
```

It checks stale evidence, a changed commit, a real fixture-test failure and repair,
and a separately observed local effect. [Coding readiness](docs/coding-readiness.md)
describes owner-configured named actions, compact per-check diagnostics, the
explicit disposable-checkout report producer, and exit codes. A favorable assessment is historical
evidence, never an execution permit.

Start with the [open questions](research/agenda.md),
[selected related work](research/related-work.md), and the first proposed
[applicability comparison](research/studies/method-applicability/README.md).
The comparison asks whether a method can remain useful where its prerequisite
holds and be restricted where it fails. It has no executable protocol or results
yet; the roadmap describes what must be built and frozen first.

The deterministic demonstration tests mechanisms. It does **not** establish
productivity gains, general transfer, model improvement or human understanding.
The [active four-arm protocol](research/studies/human-shared-method-transfer/README.md)
compares a strong baseline, personal-only, shared-only and combined environments.
It counts the full lifecycle, including failed experiments, maintenance and human
review. Its empirical status is **designed_not_run**.

- [Current architecture](docs/final-architecture.md) and [concept](docs/concept.md)
- [Agent entry](docs/agent-entry.md) and [integration](docs/agent-integration.md)
- [Migration and validation](docs/release-validation.md)
- [Security boundary](SECURITY.md) and [assurance](docs/behavior-assurance.md)
- [Historical runtime](archive/runtime-0.4/README.md) and [exact starter provenance](docs/runtime-starter-provenance.md)

## Development checks

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest discover -s examples/starter/ekk-blueprint/ekk/tests -p test_files.py -v
.venv/bin/python research/replay.py
.venv/bin/python -m unittest discover -s research/studies/human-shared-method-transfer -p test_harness.py -v
```

Apache-2.0. The public source-export path excludes active stores, personal
profiles, operational evidence, private supplied research and development Git
history. Preparing an export does not publish it.

Installation and existing-realm migration: [upgrade guide](docs/upgrading.md).
