---
release: EKK-R-0.11
target_version: "0.11.0"
phase: implementing
updated: "2026-10-11"
implementation: in_progress
technical_verification: not_run
local_delivery: not_installed
public_preparation: not_requested
public_publication: not_requested
benefit: not_claimed
---

# Current increment state

The owner asked on 2026-10-10 for 0.11 to be designed from the practice check of
the first week after 0.10.0 and from the 1.0 target, complete and polished. The
package was reviewed by four independent lenses (boundaries, domain model,
simplicity and reversibility, production risk) and a traceability critic; their
65 findings changed the plan into two steps (D-0.11-01): [0.10.1](../0.10.1/status.md)
first, then 0.11 without a fixed date. Decisions D-0.11-01 to D-0.11-24 are
recorded in the project realm as proposed by the agent; they become accepted only
with the owner's words.

## Findings and the slices that close them

The practice check (private evidence) produced the findings below in public
form. Slices `U` are in [0.10.1](../0.10.1/tasks.md); `R`, `T` and `G` in
[tasks](tasks.md). Figures marked "one rater" come from an agent's sample and
await the owner's labels.

| ID | Finding | Closed by |
| --- | --- | --- |
| F01 | A Codex profile with a third of the turns had untrusted hooks, its pre-tool guard included; nothing reported it | T09; trust is the owner's act |
| F02 | Background host sessions without a saved thread were counted as work; one became a junk record | T05; existing records listed by T06 and archived by an owner `n` (T03) |
| F03 | Subagent work was not credited to the parent | T07 for subagent writes; crediting subagent changes deferred ([tasks](tasks.md)) |
| F04 | Changes were credited by polling the workspace: a session started in a parent directory that committed in a nested worktree got no credit, the store's own commits were credited, neighbouring sessions lent changes | R02, T06 |
| F05 | Skipped episodes contained real work (about two in five, one rater), and skipping deleted their report | T06, T08 |
| F06 | Automatic titles were often not outcome statements | T08 |
| F07 | An agent's own write and the observer's outcome for the same work were stored twice | T07; superseding repeated progress writes deferred |
| F08 | Claude Code openings could not be linked: the session variable name was wrong | U01 |
| F09 | The owner's review never ran: it depended on one host's schedule, which failed and was removed | T02 |
| F10 | The review page showed only the newest items within fixed caps, listed proposed decisions once per workspace, and took about three minutes to prepare in one run | U05, T03 |
| F11 | Expiry deleted episodes in every state after 30 days, so unjudged held results would be lost from 2026-11-01 | U02 |
| F12 | Correction capture precision was about 45 % strict and 69 % lenient (one rater); injected host text and an in-word cue leaked | R01, T04 |
| F13 | Acceptance statements used the agent's clock, one lacked the host, two were weakly grounded | U04, T01 |
| F14 | `ekk accept --id` failed with an opaque error in three sessions | U04 |
| F15 | Owner decisions were recorded as agent-stated; a decision superseding an outcome could never be accepted | U03, T01; existing records judged by the owner |
| F16 | The advisor was configured but ran only on command | T19 |
| F17 | Entry on the larger product store rose from a median of about 4 s to about 16 s after a curation that moved 142 records to new revisions; a contained realm paid about 150 Git spawns per entry | T10, T11, T12 |
| F18 | Background publication took about 33 s per write; when due, the weekly audit runs inside a publication and holds the writer lock; idle drains waited 30 s | T13, T14, T15 |
| F19 | The operation journal lost rows under parallel calls | T16 |
| F20 | The worker log and request files grew without bound | T17; request compaction deferred |
| F21 | The session card printed shortened IDs that `fetch` refused | U05 |
| F22 | The private gateway, used only for reads since 2026-09-08, embeds runtime 0.8.0; its supervisor log shows failures | T20, G01 |
| F23 | Reading evidence pooled a legacy mark with the 0.10 linkage; deliveries before 0.10 carry no host or profile | U01, T18 |
| F24 | Continuation commands that agents used in September (work find, guide show, declared files) had no real use after 0.10 | T18 measures the drop; no contract change |
| F25 | About half of the ranked items related to the task (one rater); the same hub records appeared in unrelated tasks | T03 stratum, T18 metrics; ranking change deferred |
| F26 | Records hold home paths and operational details; no secret values found | T17; share-boundary scan deferred |
| F27 | A curation the owner requested changed 144 files, one owner preference's title among them | Recorded: the revision went through the writer, history is kept, no accepted record was touched |
| F28 | No per-store or per-request latency evidence, and no regression check that cannot be flaky | T15 |
| F29 | The first calls after an upgrade rebuild indexes and audit stores | T20 |
| F30 | Agent request errors and runtime defects shared one error code | U05 |
| F31 | After the curation the larger store's entry output for the same task grew about fivefold, so selection changed as well as speed | T15, T18 |
| F32 | Field use could not yet run: no labels, unstamped observer rows, no read path to observer outcomes, unpinned study source, review dialogues unbounded, no per-rule flags | U01, T02, T03, T18 |

Working as designed and kept: hook events for every completed turn in trusted
profiles and in Claude Code; profile attribution; the session card; hook latency;
parallel sessions not serializing on entry; queue health and read-back; the
hourly observer run; the owner's verbatim words in every acceptance; supersession
links in decisions; agents entering at the start of almost every bound session,
with and without hooks. Coverage changed between 0.9.1 and 0.10.0 only because a
different profile was used. One `ekk --version` call during the practice check
wrote nothing.

## Done

- R01 (2026-10-10): `ekk.correction-rule/2` beside the unchanged rule 1 in
  `src/ekk/observation.py`, with its own digest pin, per-row flags in field use
  and `baseline --rule`. A new September run reproduced rule 1 row for row
  (Codex 3753 owner messages, Claude Code 653, no row differs from the run of
  2026-10-02), which also ties the frozen 857/120 baseline to the rule-1 content
  digest it was recorded without. Rule 2's September baseline is frozen: 4297
  owner messages, 853 corrections, 121 repeated (Codex 3644/710/96, Claude Code
  653/143/25). Claude Code is partial in both baselines alike: its transcripts
  start on 2026-09-12. On the agent's labelled sample of 113 candidates
  (in-sample, one rater) rule 2 drops exactly the three injected texts and two
  in-word cues and keeps every real correction; owner labels decide (D-0.11-11).

## Pre-registered thresholds

Recorded before the 0.11 observation window; a change needs a new decision record.

### Mechanisms in the field

| Measure | Series | Threshold | Source |
| --- | --- | --- | --- |
| Entry p50 per store | `enter` durations from journal v2, journal I/O excluded | ≤ 3 s | 1.0 design, acceptance |
| Background publication p50 per store | outbox `enqueued_at` to `published_at` | ≤ 30 s | 1.0 design, larger-store target |
| Agent wait for a write | `retain` and `capture` durations | ≤ 1 s | 1.0 design, acceptance |
| Accept and decide | their own p50 | reported, no threshold | this package |
| Journal loss | abandoned begins; `ekk` invocations in transcripts without a journal row | 0; ≤ 1 % | this package |
| Review page preparation | time until the page file is written | ≤ 30 s | this package |
| Held results or corrections lost without a count | observer counters | 0 | this package |
| Hosts serving EKK on a non-active runtime | host status | 0 | this package |

Latency comparisons between 0.10 and 0.11 subtract from 0.10 durations the legacy
journal write cost measured by the bench on the same store copy (about 0.2 s).

### Labels and the comparison

| Measure | Gating series | Minimum sample | Threshold or rule |
| --- | --- | --- | --- |
| Entry precision@5 and noise | uniform stratum of sampled deliveries | 30 tasks | 1.0 thresholds |
| Archive prior | stratum where delivered and plain orders differ | 18 deliveries | Stays 0.5 only if the delivered order's owner precision@5 exceeds the plain order's by at least 0.05; otherwise 1.0 |
| Repeated corrections (primary outcome) | `ekk.correction-rule/1` over transcripts against September | full window | 1.0 threshold |
| Correction rule precision | sampled candidates, (x+a+c)/judged per rule | 40 per rule | reported; rule 2 secondary, Codex-only against September |
| Automatic outcomes | sampled usefulness of published outcomes | 30 | ≥ 0.7 |
| Rule 3 stop rule | sampled usefulness of outcomes rule 2 would have skipped | 20 | below 0.6 holds them from 0.12 |
| Skip recall | sampled skipped episodes marked "should have been kept" | 15 | ≤ 0.2 |
| Held results | sampled "keep" share | 20 | reported |
| Retention after changes | rule 3 credit | — | a mechanism property, reported apart from September's agent-retention series |

The comparison reports "insufficient n" for any measure below its minimum. The
1.0 thresholds (entry noise, owner precision@5, CLI error rate, repeated
corrections, subagent re-entry) stay in the 1.0 specification and await the
owner's confirmation; request errors are reported as a share of the CLI error rate.

### Bench baselines on copies (0.10.0, isolated homes, warm)

| Store | Wall | User CPU | Git spawns per entry |
| --- | --- | --- | --- |
| Larger product store | 11–19 s | 9–11 s | measured by T15 on 0.10.1 before changes |
| Contained project realm | 2.8–3.7 s | measured by T15 | 156 |
| Research store | 1.1–2.0 s | measured by T15 | measured by T15 |

## Next

1. Owner: answer the review prepared on 2026-10-10 (kept verbatim and applied
   with 0.10.1). The untrusted Codex profile was fixed on 2026-10-10: the owner
   trusted all five hooks, the pre-tool guard included, and its events arrive.
2. 0.10.1 (U01–U07) is done: implemented, verified and activated on 2026-10-10 at 23:26:59 UTC
   on the owner's word, a week before the planned date
   ([status](../0.10.1/status.md)). R01 is done (above).
3. P01, whose 0.10.0 window now ends at the 0.10.1 activation; R02; then T01 onward.
4. Owner choices, answered on 2026-10-10: Claude Code transcript retention raised
   to 120 days; the scheduled field-use run moved to fixed windows;
   the gateway kept, updated by G01 after 0.10.1, reconnected by the owner; the
   advisor environment copied into the EKK home (T19); the review page budget of
   about 70 marks and acceptance by standing (D-0.11-15) agreed; the thresholds
   above and the 1.0 thresholds confirmed (the owner: "well, OK").
