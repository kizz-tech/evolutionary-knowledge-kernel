# Connecting a working project to the current runtime

The user only needs to name the product and desired outcome. The agent establishes
the owner, uses an existing realm, and creates a connection only within the
authorized task. An unknown owner is not replaced with a personal realm by default.

The connection lives in `.ekk/workspace.yaml` in the product repository. This is
an example of the original format's structure; IDs must come from the actual
authorized store:

```yaml
schema: ekk.workspace/0.1
workspace_id: urn:uuid:WORKSPACE_UUID
profile: organization
bindings:
  - realm_alias: organization
    realm_id: urn:uuid:REALM_UUID
    contexts:
      - urn:uuid:CONTEXT_UUID
packs: []
execution:
  checks: []
```

`workspace_id`, `bindings`, `realm_alias`, `realm_id`, and `contexts` belong to the
original format. `profile` is a current-runtime field for selecting the local role.
Aliases are resolved by local configuration outside Git; a binding does not include
a personal path, tokens, or corporate history. The checks fields describe a
connection to the product's standard checks; merely reading a binding or pack
executes nothing.

The agent checks that the realm ID matches the profile, that contexts exist and
are authorized, and that the selected role matches the owner. Shared continuity
remains in this realm when a participant or model changes; personal entry is added
separately through an explicitly configured `home` and `--personal`. Global
`enter --cwd` resolves the single applicable portable binding. Multiple covering
declarations require explicit resolution, rather than selecting the nearest one;
an independent nested product must not automatically inherit its parent's
connection. Ambiguity, an ID mismatch, or `unbound` blocks knowledge access until
the binding is corrected. They do not authorize automatically creating another
root or returning to a personal store.

After connecting, the agent reads context, performs the bounded task with the
product's standard tools, and retains significant evidence through the safe writer.
Decision acceptance, code changes, knowledge updates, release, and an observed
outcome remain separate facts. Instructions for the actual JSON interface are in
[using.md](using.md).

A scaffold for a new client realm remains inactive until the owner, access rights,
and permitted sources are established. A local scaffold is not a corporate pilot.
Profiles under one OS user do not provide physical isolation: an actual company
connection requires an access boundary that meets its rules.

A pack update is considered separately from connection: version and digest pin the
actual artifact, and a public method becomes binding only after local acceptance.
No onboarding publishes data, deploys a product, or proves EKK's research effect.

## Activating a new owner

1. Record the actual owner, permitted access environment, and sources. Until then,
   the scaffold remains `awaiting_owner`; do not replace its `owner: null` with a guess.
2. Select a separate directory accessible to this owner outside the personal realm.
   The agent initializes it with `ekk init --root /authorized/path --title 'Owner knowledge'`.
   In the current trusted-local mode, the principal is the OS user; if company rules
   require a different boundary, provide the appropriate environment first and do
   not load the data.
3. Register the actual IDs and path in this owner's local profile. Do not copy the
   entire personal profile. Create the required context records through
   `propose/apply`, specifying their purpose and permitted sources.
4. In each authorized product repository, run
   `ekk init --workspace --cwd /path/to/product --profile ROLE --realm ALIAS --scope CONTEXT_ID`.
   An existing binding is not overwritten automatically; its ID is checked against
   the published store.
5. Run `ekk doctor --profile ROLE --realm ALIAS` and `ekk enter --cwd /path/to/product`.
   Verify access denial from an unsuitable role. Make a full backup with Git refs
   and verify restoration in a separate location before bulk ingestion.
6. Retain a small authorized source through `capture`, compare its exact bytes,
   and read it in the required context. A larger transfer uses a separate provenance
   map; sources are preserved, and acceptance is not inherited.
7. After verification, switch the product's agent entry to this binding. Explicitly
   disable the previous writer; observe the first real outcomes. Updating a pack,
   accepting a decision, and transferring data to another owner remain separate actions.

A method is transferred through `ekk method export/receive`: the recipient retains
the exact package as a source, after which their own verification and acceptance
are required. When conditions change, reconsider, quarantine, and retire are
available; the previous version is not erased. See [methods.md](methods.md).
