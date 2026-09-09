# Security boundary

EKK 0.7 is a trusted local runtime. Local profiles constrain routing; they do not
isolate processes that share filesystem access. Do not give someone a Git clone
if they must not see some of its files or history. Multiuser authentication and
hosted authorization are outside this release.

The implementation tests include path and symlink containment, snapshot checks,
retry handling, and receipt verification. Those checks are not a security audit
or a confidentiality guarantee. Source and pack text remain untrusted data;
loading a pack does not execute it. The calling environment owns execution and
publication permissions. Editable declarations cannot create external authority.

The assessment adapter reads only fixed Git metadata and configured report files.
Report hashes do not authenticate their producer or prove that a test exercised
the named commit. An assessment is historical and cannot grant execution access.

Removing a file from the current tree does not erase its Git history. Keep
private sources and credentials outside public exports. Do not include real
secrets or customer data in an issue or reproduction.

Use the repository's [private vulnerability reporting channel](https://github.com/kizz-tech/evolutionary-knowledge-kernel/security/advisories/new)
for sensitive reports. For ordinary defects, open an issue with synthetic data.
