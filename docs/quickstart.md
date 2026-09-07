# Start from a useful task

Runtime 0.5 is the current checkout. Python 3.11+ and Git are required. Install
locally and run the complete disposable method example:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python examples/method_transfer.py
```

Expected result: `status: passed` with checks for private exploration, continuity
in fresh processes, inert transfer, receiver evaluation, adverse evidence,
quarantine, retirement, next revision and historical reconstruction. The example
uses synthetic principals under one trusted OS user. It needs no API key, existing
profile or real account, performs no external delivery, and deletes its temporary
stores on exit. `--output /new/path` preserves its synthetic evidence instead.

The lower-level source/capture/propose/apply example also remains runnable:

```sh
.venv/bin/python examples/quickstart.py --ekk .venv/bin/ekk
```

## Enter existing work

A project's existing portable binding selects its authorized owner and contexts:

```sh
ekk enter --cwd /path/to/project --task 'Continue the investigation' --compact
```

The result includes accepted commitments, visible questions/results and exact
continuation anchors. Entry does not retain the intention or create obligations.
`blocked`, `incomplete`, omitted evidence and conflicts remain meaningful. An
unbound or denied project does not grant a different storage route.

## Personal entry

A local profile may explicitly configure its personal home:

```yaml
home:
  realm_alias: personal
  realm_id: EXACT_EXISTING_REALM_ID
  contexts: [EXACT_EXISTING_CONTEXT_ID]
```

This is an optional addition to an existing `ekk.profile/0.1` document outside
Git. The alias must already resolve to that exact realm ID. It does not create
or migrate a store, change ownership, or grant access. Use IDs from the owner's
actual registry; the placeholders above are not valid configuration.

Outside a project, `ekk enter --profile PROFILE --task 'Explore this question'`
can use that explicit home. Inside a bound project, add `--personal` to include
it. Personal and shared projections keep separate realm IDs, snapshots and
owner labels. A role/profile change is not a clean model session or OS isolation;
the executing client remains responsible for keeping incompatible contexts apart.

## Resume exact prior work

Take the full reference from `work_view` and supply it as JSON:

```sh
ekk enter --cwd /path/to/project --task 'Continue from this result' --resume '{"realm":"REALM_ID","id":"RECORD_ID","revision":1,"digest":"sha256:FULL_SHA256"}'
```

Replace the placeholders with the actual emitted reference. Resume forces those
exact bytes and their dependency closure into the context budget. It can retain
an old revision without presenting it as the current accepted commitment. Wrong
realm, digest, revision or current access fails; insufficient budget blocks the
projection rather than silently dropping the continuation anchor.

## Improve a method

Use `ekk method --help` and the [method guide](methods.md). The lifecycle separates
proposal, observed evaluation, local acceptance, use, authorized export, inert
receive, reconsideration and retirement. Installed methods are inert data until
a current host admission reconstructs their eligibility.

No command in this guide publishes the new runtime or activates a real company
integration. Existing stores, bindings and ownership remain intact.
