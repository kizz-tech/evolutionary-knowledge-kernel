---
release: "EKK-R-0.9"
target_version: "0.9.0"
phase: delivered_inside_1.0
updated: "2026-10-02"
implementation: runtime_0.9.0_committed
technical_verification: runtime_0.9.0_tested
local_delivery: runtime_0.9.0_installed
public_preparation: runtime_0.9.0_export_prepared
public_publication: not_requested
benefit: not_observed
current_authority: see_1.0_status
next_task: see_1.0_status
---

# Current release state

Delivered on 2026-10-02 as runtime 0.9.0 inside the 1.0 package (D-1.0-06): host
hooks, the observer, the session card, preferences as records and the review page.
The authoritative state, decisions and evidence are in the
[1.0 status](../1.0/status.md), [decisions](../1.0/decisions.md) and the
[0.9.0 release notes](../../release-notes-0.9.0.md). The text below is the planning
record as it was before implementation.

## Planning record (2026-09-21)

The owner requested a working specification and plan, including release
organization using the same principles as specs. The planning package is ready.
This request did not start runtime implementation, training, installation,
background observation or external repository creation.

Start with [T01 in the task plan](tasks.md): inspect actual host capture/delivery
capabilities and establish the implementation baseline. The design is sufficiently
specified to investigate that boundary; unknown host capabilities are not
represented as implemented promises. Planning completion is not product delivery.

## Preserved starting point

EKK 0.8 continuous work is [locally implemented](../../plans/v0.8/implementation.md).
The current source contains an independent [Laya search-advice shadow contract](../../plans/laya-advisory/status.md),
whose adapter and runtime integration remain pending in that spec. Neither is a
completed ongoing-observation workflow. Re-read their status before implementation
because concurrent work may change them.

The shared development checkout contains substantial unrelated work. No broad
commit, reset or migration was performed while preparing this package. Do not
infer the release baseline from the current HEAD alone.

## Decisions to resolve during implementation

| ID | Question / current position | Owner / resolving task | Effect if unresolved |
| --- | --- | --- | --- |
| U01 | Which supported host events arrive during work, and how can recall reach the agent at a change of focus? No hook is assumed. | Host / T01 | Blocks complete live integration; retrospective replay must be labeled separately |
| U02 | What finite capture, queue, extraction and recall budgets fit actual workloads? No latency or quality measurements exist for 0.9. | Host + EKK / T01, confirmed T07–T09 | No default live activation until bounds and failure behavior are specified |
| U03 | Which visible event sources and excerpts may be processed/retained for each owner? Existing task access is not blanket training permission. | Source owner + host / T01, T04 | Continue with permitted channels; report coverage and do not invent a fallback store |
| U04 | Which permitted RU/EN examples support the evaluation/training rubric, and which can be distributed? | Data owner + evaluation / T09 | Bounded public/declassified evaluation may proceed; private-data training/publication remains out of scope |
| U05 | Does base Laya offer useful selection, and does specialization improve it at acceptable cost? | Observer evaluation / T09–T10 | Retain baseline; report a negative or unresolved model result honestly |
| U06 | Should an observer package become a separate OSS repository; what account/name/license and public material? | Product/repository owner / T15 | Does not block local core delivery; no external repository is created implicitly |
| U07 | Which Gateway and non-primary client surfaces support acquisition versus only reading/writing? | Gateway + host / T01, T07 | Publish a coverage matrix; do not claim observation on every connected client |

Routine reversible choices can be resolved within later implementation authority
and recorded in [decisions.md](decisions.md). Escalate only a material scope,
ownership, data-use or external-action decision that the session does not already
authorize. This table is not a request for seven approvals before work can begin.

## Evidence and handoff

Planning evidence: source inspection, the linked primary research, requirement to
task mapping and a local documentation/link check. Runtime/model acceptance has
not been run. Private source hashes and the original Russian research are retained
outside the public source boundary. No new benchmark or productivity result is
claimed.

Required next handoff: actual T01 channel evidence, proposed finite budgets,
baseline snapshot ownership and any scope-changing capability gap. Later delivery
adds exact frozen versions/hashes, O01–O19 coverage, local activation/rollback and
separate model/publication/benefit states here. Detailed per-task evidence stays
in [tasks.md](tasks.md), not duplicated in another tracker.
