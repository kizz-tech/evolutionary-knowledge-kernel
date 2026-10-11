# Design: reliable continuation of real work

Date: 2026-10-05. Scope: a local runtime increment on 0.9.1. The accepted 1.0
target and canonical record format 0.1 remain the foundation.

## Intended outcome

A significant result keeps its declared grounds, is discoverable from what
happened, and lets a later session identify the selected version and the current
state. Research, design, planning and implementation can use the same continuity
path. Ordinary work needs no authored work item or record at every phase.

The preceding inspection identified four concrete gaps: historical continuation
could be navigated by an ID that opened current bytes; work-only discovery omitted
linked observations; assembling required result files needed an ad hoc script;
reading telemetry marked every recent same-realm delivery of an ID. Existing
retention, queueing, current-first entry, observer capture and owner review are
reused. Mechanism repairs do not establish comparative benefit.

## Components and owners

| Component | Responsibility | Existing owner |
| --- | --- | --- |
| Exact continuation | Keep selected historical bytes, label historical state and offer distinct exact/current navigation | Context service and display adapter |
| Event discovery | Match readable linked events and return their current parent and exact evidence | Work repository |
| Declared result assembly | Freeze explicitly selected local files into one ordinary retention request, preflight capacity and verify declared inventory | File adapter, retention writer and durable queue |
| Exact reading receipts | Record an observed exact read; associate a delivery only with established identity and version | Private experience store and host adapter |
| Optional phase guidance | Apply relevant earlier experience to a decision and define its useful output and stop condition | Existing practical guides and agent workflow |

## Continuation and discovery

Historical status and next step belong to their selected revision. Current
navigation is a separate authorized reference. Missing or unreadable current
material stays unavailable; updates still require the current exact reference.

Event matching follows established work links. Parent authorization alone does
not authorize an event or its grounds. Discovery returns bounded excerpts only
after readability checks. Earlier, unavailable and truncated coverage is explicit,
including an empty result. There is no exhaustive-absence claim from a bounded
search.

## Declared files

A manifest is request assembly, not a second package entity or lifecycle. It
selects one UTF-8 result and at most 32 explicit artifacts. It cannot select a
route, grants, commands or external effects. The CLI resolves the destination
through the ordinary bound route and displays it with the frozen inventory.

Missing files, duplicate output names, changing reads and unsupported capacity
fail before enqueueing. A pending receipt means frozen local durability. Package
completion means that the existing publication receipt and exact read-back match
every declared artifact and result body. It makes no claim about undeclared
documents or external references. Retries use the frozen bytes and logical key;
rereading changed files produces a different candidate.

## Reading and experience

A reading receipt names the exact realm, ID, revision and digest; observed host,
session, workspace and time; and the read operation. Unknown identity remains
unknown. A delivery relationship requires matching identities and exact version;
multiple eligible deliveries remain ambiguous. Legacy ID/time-window marks are
preserved with legacy semantics and are never upgraded retrospectively.

Delivery, opening, changed decision, completed action and observed helpfulness
remain separate. A phase guide helps apply a relevant case; the ordinary result
can describe the changed decision, exact grounds and actual outcome. Existing
`work event`, `improve record` and `retain` can keep significant new evidence.
`improve.stage` continues to mean delivery/use/helpfulness, not a work phase.

## Alternatives and scope

The smallest alternative repairs navigation and reading attribution, while
keeping event discovery and file assembly on their existing interfaces. The full
bounded increment also closes those two declared workflows. Neither option adds
a belief ontology, phase classifier, applied advisor, transcript knowledge store,
mandatory diary or new standing personal preferences.

Four phases are advisory decision aids, not a required waterfall. Domain and
phase are independent; existing method package identities remain unchanged.
Routing, acceptance, subject verification, host hook trust and external effects
retain their existing owners.

## Verification and revision

Use isolated tests for authorization, historical references, event coverage,
file races, frozen retries, read receipt identity, migration and unknown outcomes.
Run the required compatibility suite, then build and install an immutable local
release with its previous runtime preserved. Check real unchanged read requests
against both releases, recording deliberate display differences.

The next ordinary continuations must establish usefulness and cost. A corrected
mechanism, successful check, retained report or opened record is not that evidence.
Revisit a component when actual use shows missing context, excess work or an
inapplicable lesson; keep new evidence and counterexamples in the owning realm.
