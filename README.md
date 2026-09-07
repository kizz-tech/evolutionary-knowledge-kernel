# Evolutionary Knowledge Kernel

**A local knowledge environment for agents: keep sources, explain decisions, and revisit them when their grounds change.**

EKK is an experimental Python runtime and an open research proposal. It stores
source bytes separately from interpretations, links decisions to exact evidence,
and returns scoped context for the next task. The model stays fixed; the working
environment can change through reviewed records, methods, tools, and checks.

**The hypothesis is untested:** can this evolving environment improve a fixed
model's work across a sequence of product changes, after counting maintenance,
failed experiments, and human review?

## Try it

Start with the [runnable quickstart](docs/quickstart.md). It creates an isolated
example, captures a source, proposes and applies a change, and reads it back.
Python 3.11+ and Git are required; no model API key is needed for the local demo.
Then use the [agent integration guide](docs/agent-integration.md) with a project
and knowledge owner you control.

Runtime **0.4.0**, record format **0.1**, and method pack versions are independent.
This is the first research prerelease, published by [Kizz](https://github.com/kizz-tech)
under [Apache-2.0](LICENSE).

## What changes in everyday work

Suppose a team chose a cache because a measured request was too slow. A note that
says “use a cache” loses the reason. EKK can retain the measurement as a source,
the decision's expected effect, and a condition for reconsideration. When the
request path changes, the next task can inspect that evidence and decide whether
the cache is still useful. It can also conclude that no change is warranted.

The loop is: **context → authorized work → evidence → reviewed knowledge change
→ later reconsideration**. Ordinary edits can produce zero new records.
Writing a note does not accept a rule, deploy code, or prove an outcome.

| Available in the local runtime | Outside the current evidence |
| --- | --- |
| Exact source capture and stable references | Automatic truth or authority detection |
| Scoped context, explicit conflicts and unknowns | Guaranteed agent compliance |
| Proposals against a specific snapshot; Git writer with retry and recovery checks | Hosted service or multiuser access-control boundary |
| Versioned decisions and verified acceptance receipts | Proven productivity gains or model learning |
| Portable project bindings and local profiles | Background capture of every conversation |

## Read and reproduce

- [Concept and research question](docs/concept.md)
- [Current implementation evidence](docs/release-validation.md)
- [Architecture coverage and limits](docs/runtime-architecture-coverage.md)
- [Architecture, Russian original](docs/architecture.ru.md) and [file contract](spec/contract.md)
- [Research protocol](research/studies/001-environment-learning/protocol.yaml): `designed_not_run`
- [Release notes](docs/release-notes-0.4.md), [contributing](CONTRIBUTING.md), and [security boundary](SECURITY.md)

The exact supplied starter is preserved under `examples/starter/ekk-blueprint`.
Its design-stage wording describes that historical artifact, not the current
runtime. [Provenance](docs/runtime-starter-provenance.md) explains the boundary.
The release export contains source code and synthetic examples; active knowledge
stores, local profiles, runtime state, and development Git history are excluded.

## Development checks

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest discover -s examples/starter/ekk-blueprint/ekk/tests -p test_files.py -v
.venv/bin/python research/replay.py
```

These commands test implementation behavior. They do not run the model study.
See the validation report for the exact previously tested revision and limits.
