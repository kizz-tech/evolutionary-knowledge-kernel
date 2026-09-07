# Can an agent improve by changing its working environment?

EKK explores a specific question: with the model held fixed, can accumulated
sources, explicit decision grounds, and reviewed changes to working methods
improve performance across a sequence of product changes?

The environment contains more than remembered text. It contains the reasons a
choice was made, the result expected from it, the evidence actually observed,
and the conditions that would make the choice worth reconsidering. An agent can
propose changing a method, tool, or check, but ordinary execution tools and their
authorization still control whether that change happens.

## A concrete example

A synthetic team adds a cache after measuring slow responses. The environment
keeps the original measurement unchanged. A separate decision explains why the
cache was selected and what latency improvement was expected. A later observation
records a measured result. After a query rewrite removes the bottleneck, the
agent can inspect the grounds and propose removing unnecessary cache machinery.
This example illustrates the intended loop; it is not a measured study result.

## The implementation choices

Sources and interpretations have different records. References pin IDs,
revisions, and digests, so a changed file cannot silently become the old evidence.
Applying a proposal requires its expected snapshot; a stale base requires a new
review. Acceptance is a separate, verified operation tied to exact content and
current governance. Imported history does not become an accepted local rule.

Independent knowledge owners use separate realms. A project binding selects an
authorized context through a local profile. Those profiles guide routing within
a trusted local process; they do not isolate users who can read the same disk.
The kernel keeps semantics separate from Markdown, Git, CLI, indexes, and
execution adapters. Packs describe methods without executing code when loaded.

## What would count as evidence?

The [designed study](../research/studies/001-environment-learning/protocol.yaml)
compares four conditions: ordinary code/documentation; persistent memory and
retrieval; decision provenance, expectations, and revision; and environment
changes to tools, rules, and checks. The model, budgets, task sequences, repeat
count, and evaluation procedure must be fixed before running it.

Measure verified task quality, regressions, repeated known failures, unnecessary
interventions, total cost, and human involvement. Count context construction,
maintenance, unsuccessful experiments, and review. Keep the evaluator and held-out
answers outside the mutable agent workspace. Publish negative results too.

The experiment has **not run**. Local functional tests show properties of this
implementation. They do not establish that EKK beats documentation or memory,
that benefits grow monotonically, or that a later faster task proves learning.

## How to help

Try the isolated demo. Report a reproducible failure, a missing use case, a cost
that the protocol misses, or a simpler way to achieve the same behavior. Before
an empirical run, help turn the designed protocol into a frozen, executable
comparison. The first release is a concept, working implementation, and research
invitation, with no claim of scientific novelty or demonstrated superiority.
