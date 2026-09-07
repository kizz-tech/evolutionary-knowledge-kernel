# Supplied standard packs

The `base`, `research`, and `software` directories preserve the starter archive's
exact `pack.yaml` and `METHOD.md` bytes. Each manifest declares a version, required
format, entrypoint, proposed status and `installation_executes_code: false`.
Reading or installing these methods never grants authority or executes a command.

The original release artifact digest contract is in `docs/interfaces.md`.
A lock binds version, origin and SHA-256 of the actual distributed artifact. For a
directory artifact the runtime must specify a deterministic manifest of relative
paths and byte hashes. No hash is asserted before those bytes are computed.
Upstream versions remain candidates for local adoption, not automatic rule changes.

Supplemental method templates authored before receipt of the archive are retained
separately in `docs/runtime-method-templates/`; they are not starter pack payloads.
