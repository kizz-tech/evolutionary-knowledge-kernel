# Exact record queries for private transports

`RealmService` owns `list_contexts`, `search_records`, `fetch_record`, and
`read_source`. CLI operations `contexts`, `search`, `fetch`, and `read-source`
expose the same contract to JSON clients. A transport supplies its trusted realm
and context ceiling; callers cannot bypass current governance with a historical
reference. Every exact read verifies the reference and its readable dependencies.

Search returns a published snapshot, exact references, bounded results and
explicit coverage limits. Match terms use case-insensitive substring AND matching
across record text and eligible owned UTF-8 source bytes. It is a bounded lexical
query, not semantic retrieval. Use `next_offset` with `expected_snapshot` for the
next page; a changed base conflicts instead of silently skipping results.

Fetch takes an exact `{realm,id,revision,digest}` reference and a byte budget. It
returns the canonical Markdown, metadata, body and record path. Source reads use
the owning source reference, asset index, byte offset and limit; base64 preserves
bytes across binary data and UTF-8 boundaries. Historical source assets are read
from the exact retained snapshot, not the current filesystem path.

The CLI forms `fetch --id ID` and `read-source --id ID` read the current version
of the record with exactly that ID; a prefix is never resolved. An unknown ID is
refused as `{error: invalid_request, message, refusal: unknown_id, option}`. When
the value has at least 8 characters and starts exactly one record that a read
from the selected contexts may return (the record and its dependencies lie within
them), `record_ids` names that full ID and `next` is the same command with only
that value replaced. Several such records are counted, never listed, and a record
those contexts cannot read is never named. Every `invalid_request` names the
option or request field at fault and exits with code 2. In 0.10.1
`invalid_request` covers the option and JSON-input checks, accept and decide
declarations, unknown IDs, the context budget and the fetch byte limit. Other
validation errors, including search limits and modes and read-source byte
ranges, still report `invalid_format` until 0.11, as malformed records and files
do. Until journal v2 the operation journal records a request error as
`invalid_format` at stage `request`.

`accept` is separate from writing. Supply exact `references`, an
`expected_snapshot`, and an `idempotency_key`. The application validates the pinned
bytes and creates the ordinary canonical acceptance receipt under current
authority. An identical completed retry returns its original result; a changed
request or stale unpublished attempt conflicts. Acceptance does not authorize
external execution or establish observed benefit.

The private EKK Gateway uses these operations and the existing application/CLI
dispatch without interpreting Git, Markdown ownership, or governance itself.
Method transports share `method_cli.dispatch` and the installed host registry;
remote source text cannot install callbacks or grant host privileges.
