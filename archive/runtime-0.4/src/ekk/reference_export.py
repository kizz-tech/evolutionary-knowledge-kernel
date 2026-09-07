"""Prepare a deterministic source review export; never publish or declassify data."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import tempfile

# Explicit reviewed source paths. New files require a release-scope decision.
FILES = (
    '.gitignore',
    'LICENSE',
    'NOTICE',
    'docs/quickstart.md',
    'examples/quickstart.py',
    'docs/agent-integration.md',
    'docs/concept.md',
    'docs/release-notes-0.4.md',
    'docs/release-validation.md',
    'src/ekk/adapters/context_display.py',
    'tests/test_context_display.py',

    'CITATION.cff',
    'CONTRIBUTING.md',
    'GOVERNANCE.md',
    'README.md',
    'SECURITY.md',
    'adapters/README.md',
    'docs/agent-entry.md',
    'docs/behavior-assurance.md',
    'research/studies/sequence-learning/protocol-hardening-0.2.yaml',
    'docs/architecture.md',
    'docs/implementation.md',
    'docs/interfaces.md',
    'docs/migration.md',
    'docs/release-evidence.md',
    'docs/runtime-architecture-coverage.md',
    'docs/runtime-client-onboarding.md',
    'docs/runtime-method-templates/base/proposal.md',
    'docs/runtime-method-templates/research/proposal.md',
    'docs/runtime-method-templates/software/proposal.md',
    'docs/runtime-starter-provenance.md',
    'docs/using.md',
    'examples/starter/ekk-blueprint/ARCHITECTURE.md',
    'examples/starter/ekk-blueprint/MANIFEST.sha256.json',
    'examples/starter/ekk-blueprint/README.md',
    'examples/starter/ekk-blueprint/VALIDATION.md',
    'examples/starter/ekk-blueprint/ekk/.gitignore',
    'examples/starter/ekk-blueprint/ekk/AGENTS.md',
    'examples/starter/ekk-blueprint/ekk/CITATION.cff',
    'examples/starter/ekk-blueprint/ekk/CONTRIBUTING.md',
    'examples/starter/ekk-blueprint/ekk/GOVERNANCE.md',
    'examples/starter/ekk-blueprint/ekk/PUBLICATION.md',
    'examples/starter/ekk-blueprint/ekk/README.md',
    'examples/starter/ekk-blueprint/ekk/SECURITY.md',
    'examples/starter/ekk-blueprint/ekk/adapters/README.md',
    'examples/starter/ekk-blueprint/ekk/docs/architecture.md',
    'examples/starter/ekk-blueprint/ekk/docs/implementation.md',
    'examples/starter/ekk-blueprint/ekk/docs/interfaces.md',
    'examples/starter/ekk-blueprint/ekk/docs/migration.md',
    'examples/starter/ekk-blueprint/ekk/docs/release-evidence.md',
    'examples/starter/ekk-blueprint/ekk/knowledge/.ekk/governance.yaml',
    'examples/starter/ekk-blueprint/ekk/knowledge/.ekk/packs.lock.yaml',
    'examples/starter/ekk-blueprint/ekk/knowledge/.ekk/realm.yaml',
    'examples/starter/ekk-blueprint/ekk/knowledge/.gitignore',
    'examples/starter/ekk-blueprint/ekk/knowledge/AGENTS.md',
    'examples/starter/ekk-blueprint/ekk/knowledge/README.md',
    'examples/starter/ekk-blueprint/ekk/knowledge/contexts/root.md',
    'examples/starter/ekk-blueprint/ekk/knowledge/records/decision-example.md',
    'examples/starter/ekk-blueprint/ekk/knowledge/records/observation-example.md',
    'examples/starter/ekk-blueprint/ekk/knowledge/records/source-example.md',
    'examples/starter/ekk-blueprint/ekk/knowledge/sources/d892a16d-806a-5202-83d6-da07e0d576cb/original.txt',
    'examples/starter/ekk-blueprint/ekk/packs/base/METHOD.md',
    'examples/starter/ekk-blueprint/ekk/packs/base/pack.yaml',
    'examples/starter/ekk-blueprint/ekk/packs/research/METHOD.md',
    'examples/starter/ekk-blueprint/ekk/packs/research/pack.yaml',
    'examples/starter/ekk-blueprint/ekk/packs/software/METHOD.md',
    'examples/starter/ekk-blueprint/ekk/packs/software/pack.yaml',
    'examples/starter/ekk-blueprint/ekk/research/README.md',
    'examples/starter/ekk-blueprint/ekk/research/sources.yaml',
    'examples/starter/ekk-blueprint/ekk/research/studies/001-environment-learning/protocol.yaml',
    'examples/starter/ekk-blueprint/ekk/research/studies/001-environment-learning/report.md',
    'examples/starter/ekk-blueprint/ekk/spec/contract.md',
    'examples/starter/ekk-blueprint/ekk/spec/schemas/realm.schema.json',
    'examples/starter/ekk-blueprint/ekk/spec/schemas/receipt.schema.json',
    'examples/starter/ekk-blueprint/ekk/spec/schemas/record.schema.json',
    'examples/starter/ekk-blueprint/ekk/spec/schemas/workspace.schema.json',
    'examples/starter/ekk-blueprint/ekk/src/ekk/README.md',
    'examples/starter/ekk-blueprint/ekk/tests/fixtures/workspace.yaml',
    'examples/starter/ekk-blueprint/ekk/tests/test_files.py',
    'examples/starter/ekk-blueprint/ekk/tools/requirements.txt',
    'examples/starter/ekk-blueprint/ekk/tools/validate.py',
    'examples/starter/ekk-blueprint/project-binding/.ekk/workspace.yaml',
    'examples/starter/ekk-blueprint/project-binding/AGENTS.md',
    'examples/starter/ekk-blueprint/project-binding/README.md',
    'examples/starter/ekk-blueprint/realm-templates/organization/.ekk/governance.yaml',
    'examples/starter/ekk-blueprint/realm-templates/organization/.ekk/packs.lock.yaml',
    'examples/starter/ekk-blueprint/realm-templates/organization/.ekk/realm.yaml',
    'examples/starter/ekk-blueprint/realm-templates/organization/.gitignore',
    'examples/starter/ekk-blueprint/realm-templates/organization/AGENTS.md',
    'examples/starter/ekk-blueprint/realm-templates/organization/README.md',
    'examples/starter/ekk-blueprint/realm-templates/organization/contexts/root.md',
    'examples/starter/ekk-blueprint/realm-templates/organization/records/decision-example.md',
    'examples/starter/ekk-blueprint/realm-templates/organization/records/observation-example.md',
    'examples/starter/ekk-blueprint/realm-templates/organization/records/source-example.md',
    'examples/starter/ekk-blueprint/realm-templates/organization/sources/744ab1f0-8fb5-5ce7-a70a-5f0939ec570e/original.txt',
    'examples/starter/ekk-blueprint/realm-templates/personal/.ekk/governance.yaml',
    'examples/starter/ekk-blueprint/realm-templates/personal/.ekk/packs.lock.yaml',
    'examples/starter/ekk-blueprint/realm-templates/personal/.ekk/realm.yaml',
    'examples/starter/ekk-blueprint/realm-templates/personal/.gitignore',
    'examples/starter/ekk-blueprint/realm-templates/personal/AGENTS.md',
    'examples/starter/ekk-blueprint/realm-templates/personal/README.md',
    'examples/starter/ekk-blueprint/realm-templates/personal/contexts/root.md',
    'examples/starter/ekk-blueprint/realm-templates/personal/records/decision-example.md',
    'examples/starter/ekk-blueprint/realm-templates/personal/records/observation-example.md',
    'examples/starter/ekk-blueprint/realm-templates/personal/records/source-example.md',
    'examples/starter/ekk-blueprint/realm-templates/personal/sources/d9dda74d-4363-5760-a137-2b5506e94d9c/original.txt',
    'packs/README.md',
    'packs/base/METHOD.md',
    'packs/base/pack.yaml',
    'packs/research/METHOD.md',
    'packs/research/pack.yaml',
    'packs/software/METHOD.md',
    'packs/software/pack.yaml',
    'pyproject.toml',
    'requirements.lock',
    'research/README.md',
    'research/protocol-v0.1.md',
    'research/metrics-v0.3.md',
    'research/replay.py',
    'research/studies/001-environment-learning/protocol.yaml',
    'research/studies/001-environment-learning/report.md',
    'research/studies/sequence-learning/README.md',
    'research/studies/sequence-learning/protocol.yaml',
    'spec/contract.md',
    'spec/schemas/README.md',
    'spec/schemas/realm.schema.json',
    'spec/schemas/receipt.schema.json',
    'spec/schemas/record.schema.json',
    'spec/schemas/workspace.schema.json',
    'src/ekk/__init__.py',
    'src/ekk/__main__.py',
    'src/ekk/adapters/__init__.py',
    'src/ekk/adapters/command_line.py',
    'src/ekk/adapters/contained_store.py',
    'src/ekk/adapters/execution.py',
    'src/ekk/adapters/git_store.py',
    'src/ekk/adapters/local_profile.py',
    'src/ekk/adapters/markdown.py',
    'src/ekk/adapters/migration.py',
    'src/ekk/adapters/packs.py',
    'src/ekk/adapters/sqlite_index.py',
    'src/ekk/application/__init__.py',
    'src/ekk/application/experimentation.py',
    'src/ekk/application/service.py',
    'src/ekk/assets.py',
    'src/ekk/capabilities.py',
    'src/ekk/cli.py',
    'src/ekk/compatibility.py',
    'src/ekk/experiments.py',
    'src/ekk/federation.py',
    'src/ekk/integration.py',
    'src/ekk/kernel.py',
    'src/ekk/model/__init__.py',
    'src/ekk/model/experiments.py',
    'src/ekk/pilot.py',
    'src/ekk/ports/__init__.py',
    'src/ekk/realm_cli.py',
    'src/ekk/realm_registry.py',
    'src/ekk/realms.py',
    'src/ekk/reference_export.py',
    'src/ekk/semantics.py',
    'src/ekk/semantics_v1.py',
    'tests/test_architecture_application.py',
    'tests/test_architecture_cli.py',
    'tests/test_architecture_execution.py',
    'tests/test_architecture_migration.py',
    'tests/test_architecture_profiles.py',
    'tests/test_architecture_store.py',
    'tests/test_capabilities.py',
    'tests/test_cli.py',
    'tests/test_cli_entrypoint.py',
    'tests/test_compatibility.py',
    'tests/test_contained_store.py',
    'tests/test_experiments.py',
    'tests/test_federation.py',
    'tests/test_foundation_v2.py',
    'tests/test_integration.py',
    'tests/test_integrity.py',
    'tests/test_kernel.py',
    'tests/test_legacy_frozen.py',
    'tests/test_pilot.py',
    'tests/test_realm_registry.py',
    'tests/test_realms.py',
    'tests/test_reference_export.py',
    'tests/test_regressions.py',
)


def _source(repository, relative):
    path = repository / relative
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('Missing or linked allowlisted source: ' + relative)
    data = path.read_bytes()
    # Supplementary detection only; content review still owns publication authority.
    markers = (b'/' + b'Users/', str(Path.home()).encode() + b'/', b'.codex' + b'-work',
               b'BEGIN ' + b'PRIVATE KEY')
    if any(marker in data for marker in markers):
        raise ValueError('Private material in allowlisted file: ' + relative)
    return data


def prepare(repository, destination):
    repository = Path(repository).resolve()
    requested = Path(destination).absolute()
    if requested.is_symlink() or any(p.is_symlink() for p in requested.parents):
        raise ValueError('Export destination must not traverse symlinks')
    destination = requested.resolve()
    if destination.exists() or destination.is_relative_to(repository):
        raise ValueError('Use a new export location outside the repository')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.ekk-export-', dir=destination.parent))
    try:
        manifest = {}
        for relative in FILES:
            data = _source(repository, relative)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            manifest[relative] = hashlib.sha256(data).hexdigest()
        receipt = {'schema': 'ekk.reference-export/2', 'state': 'prepared_for_review',
                   'published': False, 'license_selected': True, 'license': 'Apache-2.0',
                   'files': manifest,
                   'data': 'Explicit source and synthetic starter fixtures only; no active knowledge store, local config, Git history, or runtime state.'}
        (staging / 'export-manifest.json').write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        os.rename(staging, destination)
        return receipt
    finally:
        if staging.exists():
            shutil.rmtree(staging)
