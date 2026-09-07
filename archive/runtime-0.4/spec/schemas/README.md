# Supplied file-profile schemas

The four schemas (`record`, `realm`, `workspace`, `receipt`) are exact bytes from
the supplied architecture starter archive. `spec/contract.md` is its exact contract.
They define the selected file profile and supersede the provisional schemas authored
before the archive arrived. No existing private records were converted by this import.

Configure Draft 2020-12 and date-time format assertion. Validate front matter apart
from Markdown body bytes. Use the original read-only validator in
`examples/starter/ekk-blueprint/ekk/tools/validate.py`; it reports structural checks
and explicitly unverified guarantees. Schema validity does not authenticate a
principal, prove historical resolution or authorize execution.

Provisional additional runtime contracts are isolated in `spec/runtime-extensions/`.
They must be reconciled with the actual runtime and original profile before use.
