# Selected related work

This reading list supports the [open agenda](agenda.md) and the first proposed
[method-applicability study](studies/method-applicability/README.md). It is a
selective primary-source review updated **2026-09-09**, concentrated on external
experience, transfer, refinement and evaluation. It is not a systematic survey of
all nine questions. These methods have not been independently reproduced by EKK.

The comparison roles below are our design judgments. They are not claims by the
papers about EKK, a ranking of systems, or proof of a research gap. Claims of a
new contribution will require a focused search against the final frozen design.

| Primary source and reviewed version | Relevance to the proposed study | Reading boundary |
| --- | --- | --- |
| [Agentic Context Engineering (ACE), 2510.04618v3](https://arxiv.org/html/2510.04618v3) | Evolving context from feedback is an important alternative. Keep online adaptation distinct from independent final evaluation. | Method, online protocol, results and limitations read; not reproduced. |
| [GEPA, 2507.19457v2](https://arxiv.org/abs/2507.19457v2) | Reflective prompt evolution is a candidate for a broader adaptation comparison. | Abstract and metadata only; this does not support detailed claims about its diagnostic behavior. |
| [AgentStream, 2608.00155v1](https://arxiv.org/html/2608.00155v1) | Task streams and model choice matter when evaluating accumulated experience. | Setup, results and limitations read; the reported settings do not establish universal improvement. |
| [AgentCL, 2606.02461v2](https://arxiv.org/html/2606.02461v2) | Controlled reuse structure and negative transfer inform compatible/incompatible cases. | Controlled streams, MemProbe and limitations read; not an implementation of our proposed intervention study. |
| [Continual Learning Bench, 2606.05661v1](https://arxiv.org/html/2606.05661v1) | Known changes in latent conditions help study obsolete experience. | Setting, metrics, results and limitations read. Recovery alone does not identify the reason a procedure stopped applying. |
| [When Continual Learning Moves to Memory, 2604.27003v1](https://arxiv.org/html/2604.27003v1) | Transfer, retained behavior and harm should be measured separately. | Task-order experiments and limitations read; the limited environments and repeats constrain generalization. |
| [SkillsBench, 2602.12670v4](https://arxiv.org/html/2602.12670v4) | Paired skill/no-skill comparisons and context controls inform baseline design. | Paired comparisons and limitations read; continuous revision after a changed premise is a different experiment. |
| [SkillAxe, 2606.10546v2](https://arxiv.org/html/2606.10546v2) | Diagnoses and refines skills, including activation and procedural behavior. It is the closest adaptive baseline selected for reproduction in this proposal. | Diagnostic loop, evaluation and limitations read. The paper notes internally consistent wrong strategies, unmodeled multi-skill interactions and reliance on LLM judges. |
| [EvoAgentBench, 2607.05202v1](https://arxiv.org/html/2607.05202v1) | Ability representations and transfer controls are relevant to applicability. | Ability cards, controls and limitations read. Its curator-assisted Anchor baseline must be labeled as using additional ability annotations if included. |
| [Generalization in Adaptive Data Analysis and Holdout Reuse, 1506.02629v2](https://arxiv.org/abs/1506.02629v2); [Science publication record](https://research.ibm.com/publications/the-reusable-holdout-preserving-validity-in-adaptive-data-analysis) | Repeated adaptive selection against an evaluation set can undermine validity. | Abstract and publication record checked; formal assumptions do not automatically hold for a changing agent environment. |

SkillAxe is a proposed reproduction, not an already integrated or defeated
baseline. Establish its available artifacts, license, exact version, configuration
and reproduction limits before using its name for a measured comparison. If only
a reimplementation is possible, label that difference. ACE and GEPA remain
broader comparison candidates; their convenience must not determine which system
is presented as the strongest alternative.

SkillsBench and SkillAxe are separate works. AgentStream and Continual Learning
Bench are also separate works with different identifiers. The links above identify
the versions actually used for this framing; newer versions require a new review.

## Current beliefs and observation before action

The [Belief Runtime contract](../docs/belief-runtime.md) and
[action-readiness comparison](studies/action-readiness/README.md) use these
additional sources. Their relevance is our design inference, not a demonstrated
EKK result. Existing baseline choices for method applicability remain unchanged.

| Primary source and reviewed version | Narrow support | Reading boundary |
| --- | --- | --- |
| [Agent-BRACE, 2605.11436v1](https://arxiv.org/html/2605.11436v1) | Studies a separate belief model and policy in partially observable text environments. | Abstract, introduction and method overview read. Joint reinforcement learning and its rewards are part of the method; adding a confidence field alone was not established as the intervention. |
| [Towards a Belief-Based World Model for LLM Agents, 2609.00455v1](https://arxiv.org/html/2609.00455v1) | Tests policy access to current beliefs alongside a simulation interface. | Abstract, methods and state-space appendix read. Relevant variables and update/transition functions are hand-specified; discovering unknown software-world variables remains outside that result. |
| [CivBench: Civilization VI, 2609.02459v1](https://arxiv.org/html/2609.02459v1) | Documents under-monitoring with an available observation interface in its protocol. | Abstract, monitoring analysis and limitations read. Small uneven sample and advisory playbook; not proof that a Belief Runtime corrects the behavior. Distinct from the Civilization V paper with a similar name. |

These works motivate a bounded comparison; none has been independently reproduced
here. The first coding experiment must measure any benefit beyond the same
ordinary preconditions, sensors and host checks available to its baseline.
