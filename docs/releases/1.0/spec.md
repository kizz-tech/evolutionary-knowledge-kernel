# EKK 1.0: past work measurably improves the next work

Release ID: `EKK-R-1.0`. Target version: **1.0.0**, a planning designation. This
specification collects goals, scope candidates and the evidence plan before the
owner selects the release scope. See [status](status.md) for what is decided.
The private owner inventory holds the complete list of wishes with their sources;
this document is its public-safe summary. The target picture and component design
are in [design.md](design.md).

## Problem

EKK 0.8 stores provenance-exact records, governs acceptance and supports durable
continuation. Field observation of ordinary agent work (September 2026, one
owner, several hosts) showed that this foundation did not yet translate into
visible benefit:

- Entry often delivered records unrelated to the task, mostly as titles without
  content, and agents rarely opened them afterwards.
- Writing a result blocked the agent for about a minute or longer; interrupted and
  contended writes were the most frequent failures, and results stopped being
  retained in the busiest project.
- Owner corrections and incidental findings were not captured unless someone
  remembered to ask, so the same corrections recurred.
- Use concentrated on one host and two projects, and no instrument showed whether
  any of it helped.

0.8.1 addressed the first two points (see the
[release notes](../../release-notes-0.8.1.md)). 1.0 is about the rest, and about
proving the result.

## Product outcome

**Experience from earlier work makes the next work better, in every host the owner
uses, without extra effort from the person, and the improvement is visible in the
logs of real work.**

| Goal | Meaning | Primary evidence |
| --- | --- | --- |
| G1. Useful entry | An agent gets the few relevant findings, decisions and open questions in seconds and within a small context budget | Field results: task-independent noise, owner-judged precision on a sample, latency, output size |
| G2. Experience without reminders | Results, owner corrections and incidental findings are kept without being asked, and recalled when the same area is touched again | Repeated-correction rate; work with results but no retention; recall delivered and used |
| G3. Everywhere | The same behaviour in each supported host; delegated work inherits context instead of re-entering; active projects are bound | Per-host adoption and outcome metrics; subagent re-entry; error rate |
| G4. Proven benefit | Benefit is measured in ordinary work from real logs, stratified by agent model and EKK version, against a fixed baseline | The field-use report, owner-labelled samples and pre-registered thresholds |
| G5. Minimal core | New capability is first expressed with existing operations; the core grows only when a simpler route demonstrably fails | Each core change names the failure it addresses and its evidence |

## Evidence plan

Benefit is established in actual work, not in mechanism tests:

1. **Field-use study.** `research/studies/field-use` reconstructs EKK episodes from
   host transcripts and the private operation journal. It reports adoption, cost,
   retrieval behaviour and reuse, by host, project, week, agent model and runtime
   version. It runs before and after each change. Raw episodes stay private.
2. **Primary outcome.** The repeated-correction rate is the share of owner
   corrections that repeat an earlier one, plus the share of tasks needing
   substantial rework. The detection rules are frozen before comparison.
3. **Reference judgments.** Each period the owner labels a small sample of entry
   results, about 30–50 tasks, for relevance.
4. **Fixed baselines.** Lexical BM25 entry, as delivered in 0.8.1, is the
   retrieval baseline. Any advisor model is compared against it on the same task
   set. A change of agent or advisor model is a new condition.
5. **Pre-registered thresholds.** Thresholds are recorded in this package before
   the comparison they gate. Mechanism tests remain necessary for integrity and
   never count as benefit.

Draft thresholds, to be confirmed by the owner:

- entry noise ≤ 10% of results;
- owner-judged precision@5 ≥ 0.6;
- entry p50 ≤ 3 s in the field;
- CLI error rate ≤ 2%;
- repeated corrections at least 30% below the September baseline;
- subagent re-entry halved.

## Scope candidates

| Zone | Candidate scope | Proposed |
| --- | --- | --- |
| Evidence | Field-use reporting, primary outcome, owner samples, thresholds | Required |
| Entry | Relevance, compact agent view and reasons (done in 0.8.1); field p50 ≤ 3 s; scoped access from any project | Required |
| Entry advisor | A replaceable small model compared in shadow against BM25, applied only after a measured gain | Desirable |
| Experience | Retention without reminders; capture of corrections and findings with their grounds and area; recall at entry and change of focus. This absorbs the [0.9 package](../0.9/spec.md) | Required |
| Decisions | One home for decisions and preferences, with history, area and revision triggers | Owner decision pending |
| Everywhere | Codex, Claude Code and gateway clients at parity; delegated context handoff; project binding; one install/connect/update/disconnect path | Required |
| Reliability and cost | Error rate, latency of frequent operations, artifact retention, rollback drill | Required |
| Team | A second person or installation continues work without the author's history | Desirable |
| Methods, belief runtime | Further concept work with evidence gates | Research |
| Dependent-work revision (EKK-Q-REP) | Repair of consequences when grounds change | Research |

## Exclusions

- No mandatory reflection, universal memory lookup or record after every task.
  Routine work keeps its zero-call path.
- No second canonical store and no transcript import as knowledge.
- No claim of productivity, model improvement or human understanding from
  mechanism tests or from one owner's logs without the stated comparison.
- No automatic publication. Publication, deployment and external accounts keep
  their own authority.

## Acceptance

Acceptance is finalized when the owner selects the scope. A selected required zone
is accepted when its slice in [tasks](tasks.md) is verified and the field-use
comparison meets its pre-registered threshold for the declared observation
window. A threshold that is not met is reported as such. It is not redefined
after the fact.
