# Evolutionary Knowledge Kernel

**A personal way into work, shared continuity, and methods that can improve with experience.**

Start from an intention: investigate a question, continue a change, or prepare a
handoff. EKK returns authorized context, accepted commitments, results, questions
and exact continuation references. Personal drafts stay with their owner; shared
work can continue when its participants or agents change.

The research focus is whether useful ways of working can **persist, transfer and
be revised or retired**. More stored text is not itself an improvement. An
accepted record is not an execution permit or proof that a person understands it.

This English research preview is version **0.5.0**. Read the
[release notes](docs/release-notes-0.5.md) for compatibility changes and
[translation provenance](docs/runtime-starter-provenance.md) for preserved originals.

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

## What the three parts do

| Part | Responsibility | Owning state |
| --- | --- | --- |
| Personal entry | Start from intent, read private drafts, continue exact prior work | Explicit personal route and owner-held records |
| Shared continuity | Preserve accepted results, commitments, grounds and continuation anchors | Project realm, Git and other owning systems |
| Revisable methods | Evaluate, admit, use, transfer, reconsider and retire an exact method | Ordinary records and receipts; host-owned execution evidence |

The local kernel retains stable IDs, exact source bytes, versions, provenance,
controlled writes and acceptance receipts. The record format remains **0.1**.
Runtime **0.5.0** has one active CLI; old runtimes are explicit historical replay
artifacts outside the installed package. No company data is moved into personal
storage by entry or this migration.

The installed method adapter is deliberately small and read-only. EKK does not
rebuild identity management, a task tracker or universal approvals. External
execution, credentials, permissions and publication remain with their owning
systems. Profiles select routes within a trusted local process; they are not an
OS sandbox.

## Evidence and research

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
- [Historical runtime](archive/runtime-0.4/README.md) and [starter translation provenance](docs/runtime-starter-provenance.md)

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
