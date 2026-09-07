# Future engine

There is no hidden finished implementation here. Create modules as you work through
`docs/implementation.md`: model, application, ports, adapters, and cli.py.
Start with one Python package. There is no need to create empty interfaces and classes for every
theoretical future backend.

Dependency direction: adapters → application → model. Domain methods belong
in packs; the core does not know company-specific terms. Rules for authorization,
integrity, and snapshot validity are not delegated to the LLM.
