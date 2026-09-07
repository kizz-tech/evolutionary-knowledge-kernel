# EKK: specification and starter kit

Start with `ARCHITECTURE.md`, then open `ekk/docs/implementation.md`.
`ekk/docs/architecture.md` is the source architecture document for the future repository;
the top-level `ARCHITECTURE.md` is its exported copy for reading outside the repository.

The kit includes a proposed public project structure, a normative draft, schemas,
a synthetic public realm, personal and corporate examples, a workspace binding,
three initial packs, an implementation plan, a migration contract, a research protocol,
and an executable **read-only validator for file examples** with tests.

A full runtime, the `ekk` CLI, server isolation, a CAS writer, a migrator, and an agent scheduler
are not present yet. The proposed commands describe an interface to implement, not available programs.
No files from your LIFEOS or company were transferred. No GitHub repositories were created.
All IDs, acceptances, and metrics in the examples are illustrative; there are no verified research results.

## What actually runs

From the `ekk/` directory, in a Python environment with PyYAML and jsonschema:

```bash
python tools/validate.py knowledge
python tools/validate.py ../realm-templates/personal
python tools/validate.py ../realm-templates/organization
python -m unittest discover -s tests -v
```

Dependencies are listed in `ekk/tools/requirements.txt`. The validator does not use the network.
It checks structure, local references, available source hashes, and receipt binding to content.
It **does not prove** the truth of the text, the author's authority, ACL security, productivity,
or the correctness of a future runtime. The report explicitly returns these limitations.

The examples must not be used as one shared working vault. They illustrate **separate repositories**.
When creating a real realm, the agent assigns a new realm ID, new context IDs, and the actual owner.
A public example does not make your real data public.

Before publication, confirm rights and the chosen license. The kit does not make legal decisions
for the owner and contains no fabricated LICENSE, DOI, or list of research results.
