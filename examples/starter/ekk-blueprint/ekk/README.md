# EKK: Evolutionary Knowledge Kernel

**Status: design specification and verifiable file examples.**

EKK is being designed as a portable environment for preserving the grounds for decisions and revising
knowledge, tools, and processes based on observed consequences. The effectiveness of this architecture
has yet to be measured.

Read `docs/architecture.md` and `spec/contract.md` first, then `docs/implementation.md`.
The format is designed for independent realms, not a shared directory of personal and corporate data.

This version implements only a read-only example validator: `python tools/validate.py knowledge`.
The product CLI `ekk` is not implemented yet. Instructions must not present future commands as working ones.

`knowledge/` contains a synthetic public starter realm for the project.
`research/` contains methodology, but no research results.
`packs/` contains proposed methods that do not execute code when read or installed.

There is no automatic telemetry transmission, automatic connection of personal databases,
or granting the model access to other realms.
