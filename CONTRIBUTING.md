# Contributing

Start with a concrete problem, reproducible example, and expected behavior.
Prefer the smallest complete change. Explain what evidence would show it works.

## Choose a bounded contribution

The [open research agenda](research/agenda.md) gives stable `EKK-Q-*` question IDs.
The [roadmap](ROADMAP.md) lists `EKK-T-*` tasks, dependencies and completion
criteria. Use an ID when it helps connect a contribution to a decision; a useful
bug report does not need a research label.

Good starting points include a compatible/incompatible case for the
[applicability study](research/studies/method-applicability/README.md), a baseline
reproduction with exact versions and limits, an independent task family, a
counterexample, or a review of evaluator independence and complete costs. A
negative result or evidence for a cheaper alternative is welcome.

For a research proposal or result, include:

- The question, concrete setting and decision this could change.
- The strongest relevant alternative and what differs between comparisons.
- Task/data rights, exact versions, a reproduction command and available artifacts.
- What was proposed, implemented or actually observed; independent evaluation,
  denominators, uncertainty, failures and full costs where measured.
- A completion criterion or observation that would challenge the hypothesis.

For a bug, a minimal synthetic reproduction and expected/observed behavior are
enough. Use a [GitHub issue](https://github.com/kizz-tech/evolutionary-knowledge-kernel/issues)
for a proposed study or substantial change, and a pull request for a bounded
implementation or documentation contribution. There is no standing participant
cohort or funded study to join; a real study needs an identified owner and its own
participation, data and cost decisions.

## Checks and evidence

Run the relevant checks from the README. Format changes need compatible examples,
negative cases, and a migration contract. Method changes need a comparison that
counts maintenance and review cost. Documentation must distinguish a proposed
behavior, a tested implementation property, and an observed external outcome.

Keep original starter files unchanged; propose runtime behavior and commentary
in current files. Do not include private sources, credentials, customer material,
or content you cannot share. Synthetic reproductions are preferred.

This project uses [Apache-2.0](LICENSE). Contributions intentionally submitted for
inclusion are under those terms unless explicitly stated otherwise. Open an issue
or pull request in the Kizz repository with a synthetic reproduction or proposal.
