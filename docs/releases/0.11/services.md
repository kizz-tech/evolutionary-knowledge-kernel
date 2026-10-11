# Services and boundaries

0.10.1 and 0.11 touch one repository (this one), optionally one private
connector project (the gateway, if the owner keeps it) and the hosts' own
configuration, which stays the owner's. The model and application layers stay
independent of files, Git, processes and host formats; everything host-specific
is an adapter behind a port. An import-boundary test enforces that `ekk/model`
and `ekk/application` import no adapters, `subprocess`, `sqlite3` or file IO.

## Components

| Component | Owner | Responsibility | Does not |
| --- | --- | --- | --- |
| Host identity (`adapters/host_identity.py`, new in 0.10.1) | EKK | The one (host, profile, session) resolver for hooks, journal, notes, accept, decide and review; session variables declared per host in the registry | Decide provenance |
| Rules (`observation.py`) | EKK | Digest-pinned pure rules: correction rule 1 (frozen) and rule 2, `ekk.session-change/1` over normalized events, title rule 1, redaction rule 3 | Read files or host formats |
| Host transcripts (`adapters/host_transcripts.py`, new) | EKK | Per-host normalizers versioned as collector rules; incremental reader with an injected cursor store; owner-work property; `credited_changes` with an injected repository resolver; locating owner words | Decide dispositions; store text |
| Host connection and health (`adapters/host_hooks.py`, from `observe_cli`) | EKK | Connect, update, disconnect; health states from opaque trust values and liveness, computed by the observer run; connectors and Codex enrollment in an installer-owned `ekk.connectors/0.1` file; stable launcher path in hook commands | Compute or write Codex trust; read the caller registry's file for enrollment |
| Observer (`adapters/experience.py` orchestration, `adapters/experience_store.py`, `adapters/observe_hook.py`, `application/experience.py`) | EKK | Episode rule 3 with rule 2 shadow, links, titles, expiry and text-free rows, review state, runtime stamps, migrations with `user_version`, the read-only accessor | Publish without the writer; schedule anything |
| Review (`adapters/observe_cli.py`, `application/experience.py`) | EKK | Sample-first page, protected sample, backlog, marks and groups, effects of "no", declared provenance, review dialogue bound, advisor after the page | Decide for the owner |
| Authority (`application/service.py`) | EKK | `decision_queue`, `accept_current`, acceptance by standing, validation of a supplied `spoken_at` | Locate words in transcripts; change the record format or existing receipts |
| Store read path (`application/service.py`, `adapters/git_store.py`, `adapters/contained_store.py`, `adapters/history_index.py`, `adapters/derived_cache.py`) | EKK | Pins through the version index, lazy read-only commit views with bounded memos, one object reader per operation, `.git/HEAD` binding, lazy published views, cached ranking vectors | Change results |
| Writer and worker (`adapters/retention.py`, `adapters/operational_store.py`, `adapters/activity_cli.py`) | EKK | One validated view per publication, incremental trees with the pre-reference check, hand-off rules, audit after publication, per-request latency | Relax a byte-exact check |
| Operation journal (`adapters/operation_journal.py`, `adapters/operation_diagnostics.py`) | EKK | Journal v2 outside the legacy directory, abandoned begins, merged reports | Touch the legacy file |
| Release identity (`adapters/runtime_release.py`, new) | EKK | `active_release()` from `cli/current` and its build record, as a file contract any process can read | Activate or roll back |
| Host facade (`ekk/host_api.py`, new in 0.10.1) | EKK | The declared surface for a long-lived host, with pinned signatures | Expose adapters |
| Installer (`tools/local_install.py`) | EKK | Warm the staged release before the switch, checkpoints per verifier, rollback drill, connector hooks that never refuse | Touch an external account |
| Field use (`research/studies/field-use`) | EKK research | Runtime windows from manifests, strata, both change series through the shared credit, observer data through the read-only accessor, rule 2 baseline, minimum-n reporting, hub, displacement and output-size metrics | Pool across windows; claim benefit; write observer state |
| Gateway (private project, kept by the owner) | Gateway | Import only the facade, build from the exact release wheel, preflight digest check, `runtime_superseded` with a pause marker, no automatic reconnect; the owner reconnects | Embed a pinned EKK version |
| Codex profiles and Claude settings | Owner | Trust of hooks, transcript retention, running the hosts | — |

## Ports

- Normalized session events: produced by `host_transcripts`, consumed by the
  `session-change` predicate and by `credited_changes`; the observer and field use
  depend on these, not on host formats.
- `HostConnector` with `check`, `update` (returning the owner actions it caused),
  `connect`, `disconnect`, implemented by the Codex, Claude Code and launch-agent
  adapters and, if kept, by the gateway's own commands.
- `SemanticAdvice` stays the advisor port; review is its only new caller.

## Integration order

1. 0.10.1: host identity and the observer schema, explicit expiry, declared
   provenance and `accept --id`, interface fixes; gate and activate (done on 2026-10-10).
2. 0.11 research steps that cannot wait for transcripts: correction rule 2 and its
   September baseline; the normalizers, the change predicate and the replay's
   frozen change facts.
3. Review and authority, so the owner can judge both rules on the same items before
   rule 3 changes what reaches the review.
4. Capture (owner work, rule 3, links, titles), then host health.
5. The read path (L1 to L3), then publication, hand-off and audit, then the journal.
   They share the store adapters and are ordered so each step is equivalence-tested
   on its own.
6. Evidence readiness, activation warm and the rollback drill, documentation, the
   gate and delivery. The gateway follows its owner choice, outside the gate.
