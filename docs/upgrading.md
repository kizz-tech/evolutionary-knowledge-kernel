# Installing, upgrading and recovering EKK 0.9

Install the reviewed wheel into a new Python environment and verify its published
SHA-256 before changing the launcher. Keep the previous environment available
until the new installation has passed its isolated checks. Do not install over a
running writer. The CLI uses POSIX filesystem facilities; native Windows is not
validated. Python 3.11 or later is required.

```sh
python3 -m venv /absolute/path/to/ekk-0.9
/absolute/path/to/ekk-0.9/bin/pip install /absolute/path/to/evolutionary_knowledge_kernel-0.9.1-py3-none-any.whl
/absolute/path/to/ekk-0.9/bin/pip check
/absolute/path/to/ekk-0.9/bin/ekk --version
```

A package update changes application code. It does not authorize changes to realm
identity, record format, accepted decisions, pack locks, profile membership or
external execution permissions. Keep your existing profiles and exact references.
The record format remains `ekk.record/0.1`.

## English 0.5 and original-pack 0.6 installations

The public English edition bundles `0.1.0-design.en` packs. An existing realm
pinning those exact bytes uses the bundled provider with `EKK_PACK_DIRECTORY`
unset. Validate that its pack artifact hashes still match before switching the
normal launcher.

Some earlier local installations use the original `0.1.0-design` packs. Preserve
those exact payloads from the verified previous distribution in an owner-controlled
directory before retiring its environment. For those realms only, set the
process-local host installation option:

```sh
EKK_PACK_DIRECTORY=/absolute/path/to/preserved-original-packs \
  /absolute/path/to/ekk-0.7/bin/ekk doctor --profile PROFILE --realm ALIAS
```

The directory contains `base/`, `research/` and `software/` pack directories.
It must be an existing absolute directory and must not itself be a symlink.
Invalid configuration fails immediately; there is no automatic fallback. The
adapter still validates exact pack identity, version and the complete artifact
SHA against each realm's lock. A changed, added or missing payload fails that
validation. Protect this directory from accidental modification and preserve its
inventory and the distribution digest separately.

The option is host environment configuration, never record content or request
JSON. One process selects one provider. Scope it to a launcher for the corresponding
realms; setting it globally also changes which packs a new realm would pin. A
long-lived application serving different pack families must inject the appropriate
provider when constructing each service. Do not change a realm's pack lock merely
to make an installation pass. A translation is a different versioned artifact,
and adopting it requires a separate owner-authorized configuration change.

## Isolated proof before switching the launcher

1. Test `doctor`, bound `enter`, exact `fetch` and source readback with the new
   package. Compare realm identity, publication revision, control bytes and sources
   before and after read-only operations. Do not replace a denied route with an
   administrative root override.
2. On a disposable fixture or an explicitly authorized isolated copy, exercise
   retention, identical retry, exact continuation and diagnostics. Run the installed
   coding-readiness and method-transfer examples from the reviewed source export.
3. With full owner authority, create a backup and keep its returned digest. Restore
   to new isolated realm/runtime paths using the same matching provider. Verify
   exact published history and source bytes. Restore does not repoint the active
   profile or confer execution permission. A contained realm backup additionally
   requires explicit authority for its enclosing repository history.
4. Preserve the previous installation and provider for rollback. Point only the
   intended launcher to the new executable after validation. To undo a package
   switch, restore that launcher; if any new writes occurred, verify old-version
   compatibility or perform an owner-reviewed restore instead of assuming rollback.

Uninstalling the Python package removes application files from that environment;
it must not delete realms, profiles, backups or preserved pack providers. Verify
those paths and retain the previous launcher target. Do not operate two writers on
the same canonical realm during a migration.

## 0.9.0: side-by-side releases, warm-up and hooks

`tools/local_install.py build --build-python PY` builds a release directory from a
committed source beside the active one, `activate RELEASE_DIR` switches the
launcher with a recorded rollback, and `rollback` returns to the previous release.
After activation run `tools/local_install.py warm`: it audits every store named in
the local profiles and builds their version index, so the first write and the
first historical reference after an upgrade do not pay for it.

Register the host hooks only once 0.9.0 is active: `ekk observe install --host
claude-code`, and `ekk observe install --host codex --home PROFILE_DIR` for each
Codex profile (Codex runs a new hook after the owner trusts it). The registered
command cannot fail the host, so a rollback to an earlier runtime leaves the hooks
inert. 0.9.0 adds two private directories that can be deleted at any time:
`<data home>/observed` (the event spool and observer state) and
`<cache home>/observed/cards` (session cards). `ekk observe off` stops observation;
`ekk observe status` shows what was captured.

## 0.9.1: provenance, decisions and the hourly run

`ekk observe prefer --reported-by-agent` is gone. A preference recorded from the
command line now says who stated it: `--stated-by agent` (the default, the
agent's own reading) or `--stated-by owner-relayed --statement-session ID` (an
agent relaying the owner's words from a host session). Only the weekly review
page records `owner`; a preference recorded from a terminal no longer reaches
session cards by itself. `--owner-wide` writes to the owner's personal realm and
needs a profile and a realm alias named `personal` in the local registry.

`ekk decide` records a decision as an unaccepted record; `ekk accept` takes
`--statement-file` with the owner's word; `ekk project decisions` renders a
realm's decision records as a table. `ekk observe install --host launchd`
registers an optional hourly observer run (`ekk observe uninstall --host
launchd` removes it); it reads the same private observer directory as the hooks.

See [release validation](release-validation.md) for the exact versions and checks
actually exercised. Mechanism tests do not establish external outcomes or benefit.
