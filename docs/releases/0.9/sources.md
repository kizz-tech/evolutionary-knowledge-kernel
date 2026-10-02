# Sources and design rationale

Reviewed for this proposal on 2026-09-21. This is a selective primary-source
review, not a systematic novelty claim or independent reproduction. Research
findings inform the design; they do not establish EKK benefit.

## Existing project contracts

- [0.8 specification](../../plans/v0.8/spec.md) and [delivery state](../../plans/v0.8/implementation.md): proportionate work, continuity and recoverable publication.
- [Continuous work](../../continuous-work.md): observations and selected-episode improvement already have durable paths.
- [Concept](../../concept.md) and [Belief Runtime](../../belief-runtime.md): evidence, interpretations, currentness and authority remain distinct.
- [Methods](../../methods.md): retaining an episode does not admit a reusable method.
- [Laya advisory specification](../../plans/laya-advisory/spec.md) and [status](../../plans/laya-advisory/status.md): existing fallible search-advice envelope, without live integration.
- [Research agenda](../../../research/agenda.md): sustained experience, intervention choice, current understanding, mistaken-knowledge repair and evaluation remain open questions.
- [Release preparation](../../releasing.md): reviewed English export, source boundary and exact-artifact evidence.

Inspected code includes `application/work.py`, `application/improvement.py`,
`application/beliefs.py`, `application/semantic_shadow.py`, `application/service.py`
review semantics, `adapters/work_repository.py`, and the extensible record schema.
These are existing seams, not completed implementations of this release.

## External basis and limits

| Source | Design relevance | Reading/evidence boundary |
| --- | --- | --- |
| [Aamodt & Plaza, case-based reasoning, 1994](https://www.iiia.csic.es/~enric/papers/Aamodt_1994_Case.pdf) | Recall, adaptation, revision and retaining useful cases | Cycle and task decomposition; not an LLM experiment |
| [Kahneman & Klein, intuitive expertise, 2009](https://www.researchgate.net/publication/26798603_Conditions_for_Intuitive_Expertise) | Environmental regularity and feedback matter more than confidence alone | Abstract/conclusions; human findings provide an analogy, not EKK validation |
| [Zacks et al., event perception, 2007](https://pmc.ncbi.nlm.nih.gov/articles/PMC2852534/) | Meaningful episode boundaries | Theory/overview; no claim of biological equivalence |
| [Scullin et al., prospective memory, 2010](https://pubmed.ncbi.nlm.nih.gov/20053054/) | Recall at a relevant cue without constant active monitoring | Abstract; software trigger design is our inference |
| [ExpeL, v3](https://arxiv.org/html/2308.10144v3) | Cross-task insights from experience | Introduction, extraction overview and limitations |
| [ReasoningBank, v1](https://arxiv.org/html/2509.25140v1) | Transferable lessons from successful and failed trajectories | Methods, reported task settings and judge/retrieval limitations; not reproduced |
| [ACE, v3](https://arxiv.org/html/2510.04618v3) | Localized context updates; avoid losing details through repeated full rewriting | Motivation and incremental-update method |
| [Nemori, v1](https://arxiv.org/html/2508.03341v1) | Episode formation and prediction gaps checked against original conversation | Segmentation/predict-calibrate method; conversational benchmarks |
| [Hindsight, v1](https://arxiv.org/html/2512.12818v1) | Separate experience, evidence, summaries and beliefs; contextual retrieval | Initial paper architecture, not an audit of all current product behavior |
| [Mastra Observational Memory](https://mastra.ai/research/observational-memory) | Separate observer/reflector and bounded context | Author engineering report and methodology; conversational-memory results |
| [Letta sleep-time compute](https://www.letta.com/blog/sleep-time-compute/) | Move memory processing outside the main interaction | Author architecture description; no inferred EKK speedup |
| [MemRL, v1](https://arxiv.org/html/2601.03192v1) | Similarity and usefulness are different selection objectives | Retrieval/utility methods; ordinary work lacks its ready reward signal |
| [LongMemEval](https://arxiv.org/abs/2410.10813) | Useful evaluation boundary for conversational memory | Does not directly measure noticing engineering risk before a later decision |
| [MemoryGraft](https://arxiv.org/abs/2512.16962) | Retrieved experience can persist untrusted behavioral instructions | Abstract and stated attack setting, not measured EKK exposure |
| [Laya model card](https://huggingface.co/convaiinnovations/laya) and [Laya-MLX](https://github.com/mizorewww/laya-mlx) | Typed decision architecture, constrained inputs, calibration and runtime boundary | Model documentation and installed package metadata; no 0.9 quality experiment |

Earlier owner-supplied research and the detailed Russian working review informed
this technical synthesis. Original private text, local model/config paths, source
hashes and operational examples remain in the private planning handoff; they are
not implicitly cleared for public export. The observation proposal was previously
retained as research, not adopted as a runtime commitment.
