# Laya advisory status

| Task | Status | Evidence |
| --- | --- | --- |
| T0 Specification | Complete | `spec.md`, `tasks.md`, `decisions.md` |
| T1 Shadow contract | Complete | `src/ekk/ports/semantic_advisory.py`, `src/ekk/application/semantic_shadow.py`; 6 focused tests pass |
| T2 Local adapter | Complete as a model-neutral process adapter | `src/ekk/adapters/advisor_process.py`, `tools/advisors/gliner_decide.py`, `src/ekk/application/triage_shadow.py`; focused tests pass; not wired into a CLI or runtime path |
| T3 Evaluation fixtures | Pending | |
| T4 Offline evaluation | Pending | |
| T5 Search shadow integration | Pending | |
| T6 Fine-tuned checkpoint | Pending | |
| T7 Applied reranking study | Pending | |

No live search, context assembly, retention, acceptance, or execution behavior has
changed. No empirical benefit is claimed.

The completed T1 slice validates an opaque bounded advisor request, preserves the
original baseline and exact references, contains unavailable or malformed model
output, marks `applied: false` and `authority_effect: none`, and requires agent
exact-read recheck. It is not wired into a CLI or runtime path.

The active advisor is a replaceable small model behind the semantic-advice port
(1.0 decisions D-1.0-01 and D-1.0-02); Laya is no longer the active candidate
and the current choice is GLiNER2.5-Decide. The model runs in its own process
and environment, selected by a private `advisor.json`; swapping models changes
that file and the process script, not EKK. The same adapter serves a second
shadow contract, `ekk.triage-shadow/0.1`, which labels short observed texts as
correction, decision, finding or noise. Both remain shadow-only until compared
with the lexical baseline on real tasks and owner samples.
