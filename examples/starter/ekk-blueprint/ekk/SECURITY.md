# Security boundary

This kit does not contain a production access controller. The validator does not verify identity,
the author's authority, or text confidentiality. Do not give employees a full Git clone
if they are prohibited from accessing some of its files or history.

Sources are untrusted. Packs do not execute code when loaded. A future runtime requires
checks for path traversal, symlink escape, permitted sources, CAS, cache isolation, and access revocation.
The server principal is established by transport and authorization, not input YAML.

Do not use public issues for real secrets or customer data.
Maintainers must provide a private vulnerability reporting contact before the public release.
