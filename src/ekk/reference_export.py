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
    'CITATION.cff',
    'CONTRIBUTING.md',
    'GOVERNANCE.md',
    'LICENSE',
    'NOTICE',
    'README.md',
    'ROADMAP.md',
    'SECURITY.md',
    'adapters/README.md',
    'archive/runtime-0.4/MANIFEST.sha256.json',
    'archive/runtime-0.4/README.md',
    'archive/runtime-0.4/packs/README.md',
    'archive/runtime-0.4/packs/base/METHOD.md',
    'archive/runtime-0.4/packs/base/pack.yaml',
    'archive/runtime-0.4/packs/research/METHOD.md',
    'archive/runtime-0.4/packs/research/pack.yaml',
    'archive/runtime-0.4/packs/software/METHOD.md',
    'archive/runtime-0.4/packs/software/pack.yaml',
    'archive/runtime-0.4/replay.py',
    'archive/runtime-0.4/spec/contract.md',
    'archive/runtime-0.4/spec/runtime-extensions/README.md',
    'archive/runtime-0.4/spec/runtime-extensions/changeset.schema.json',
    'archive/runtime-0.4/spec/runtime-extensions/governance.schema.json',
    'archive/runtime-0.4/spec/runtime-extensions/pack.schema.json',
    'archive/runtime-0.4/spec/runtime-extensions/packs.schema.json',
    'archive/runtime-0.4/spec/schemas/README.md',
    'archive/runtime-0.4/spec/schemas/realm.schema.json',
    'archive/runtime-0.4/spec/schemas/receipt.schema.json',
    'archive/runtime-0.4/spec/schemas/record.schema.json',
    'archive/runtime-0.4/spec/schemas/workspace.schema.json',
    'archive/runtime-0.4/src/ekk/__init__.py',
    'archive/runtime-0.4/src/ekk/__main__.py',
    'archive/runtime-0.4/src/ekk/adapters/__init__.py',
    'archive/runtime-0.4/src/ekk/adapters/command_line.py',
    'archive/runtime-0.4/src/ekk/adapters/contained_store.py',
    'archive/runtime-0.4/src/ekk/adapters/context_display.py',
    'archive/runtime-0.4/src/ekk/adapters/execution.py',
    'archive/runtime-0.4/src/ekk/adapters/git_store.py',
    'archive/runtime-0.4/src/ekk/adapters/local_profile.py',
    'archive/runtime-0.4/src/ekk/adapters/markdown.py',
    'archive/runtime-0.4/src/ekk/adapters/migration.py',
    'archive/runtime-0.4/src/ekk/adapters/packs.py',
    'archive/runtime-0.4/src/ekk/adapters/sqlite_index.py',
    'archive/runtime-0.4/src/ekk/application/__init__.py',
    'archive/runtime-0.4/src/ekk/application/experimentation.py',
    'archive/runtime-0.4/src/ekk/application/service.py',
    'archive/runtime-0.4/src/ekk/assets.py',
    'archive/runtime-0.4/src/ekk/capabilities.py',
    'archive/runtime-0.4/src/ekk/cli.py',
    'archive/runtime-0.4/src/ekk/compatibility.py',
    'archive/runtime-0.4/src/ekk/experiments.py',
    'archive/runtime-0.4/src/ekk/federation.py',
    'archive/runtime-0.4/src/ekk/integration.py',
    'archive/runtime-0.4/src/ekk/kernel.py',
    'archive/runtime-0.4/src/ekk/model/__init__.py',
    'archive/runtime-0.4/src/ekk/model/experiments.py',
    'archive/runtime-0.4/src/ekk/pilot.py',
    'archive/runtime-0.4/src/ekk/ports/__init__.py',
    'archive/runtime-0.4/src/ekk/realm_cli.py',
    'archive/runtime-0.4/src/ekk/realm_registry.py',
    'archive/runtime-0.4/src/ekk/realms.py',
    'archive/runtime-0.4/src/ekk/reference_export.py',
    'archive/runtime-0.4/src/ekk/semantics.py',
    'archive/runtime-0.4/src/ekk/semantics_v1.py',
    'archive/runtime-0.4/tests/test_cli.py',
    'archive/runtime-0.4/tests/test_compatibility.py',
    'archive/runtime-0.4/tests/test_federation.py',
    'archive/runtime-0.4/tests/test_foundation_v2.py',
    'archive/runtime-0.4/tests/test_integration.py',
    'archive/runtime-0.4/tests/test_integrity.py',
    'archive/runtime-0.4/tests/test_kernel.py',
    'archive/runtime-0.4/tests/test_legacy_frozen.py',
    'archive/runtime-0.4/tests/test_pilot.py',
    'archive/runtime-0.4/tests/test_realm_registry.py',
    'archive/runtime-0.4/tests/test_realms.py',
    'archive/runtime-0.4/tests/test_regressions.py',
    'docs/agent-entry.md',
    'docs/historical-reading.md',
    'docs/agent-integration.md',
    'docs/architecture.ru.md',
    'docs/behavior-assurance.md',
    'docs/belief-runtime.md',
    'docs/coding-readiness.md',
    'src/ekk/application/beliefs.py',
    'src/ekk/application/coding_readiness.py',
    'src/ekk/adapters/coding_assessment.py',
    'examples/action_readiness.py',
    'examples/coding_readiness.py',
    'tests/test_beliefs.py',
    'tests/test_coding_assessment.py',
    'tests/test_action_context.py',
    'tests/test_check_report.py',
    'tools/check_report.py',
    'docs/concept.md',
    'docs/final-architecture.md',
    'docs/implementation.ru.md',
    'docs/interfaces.ru.md',
    'docs/methods.md',
    'docs/migration.ru.md',
    'docs/quickstart.md',
    'docs/release-evidence.ru.md',
    'docs/release-notes-0.4.md',
    'docs/release-notes-0.5.md',
    'docs/release-validation.md',
    'docs/runtime-architecture-coverage.md',
    'docs/runtime-client-onboarding.ru.md',
    'docs/runtime-method-templates/base/proposal.md',
    'docs/runtime-method-templates/research/proposal.md',
    'docs/runtime-method-templates/software/proposal.md',
    'docs/runtime-starter-provenance.md',
    'docs/using.md',
    'examples/method_transfer.py',
    'examples/quickstart.py',
    'examples/starter/ekk-blueprint/ARCHITECTURE.ru.md',
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
    'examples/starter/ekk-blueprint/ekk/docs/architecture.ru.md',
    'examples/starter/ekk-blueprint/ekk/docs/implementation.ru.md',
    'examples/starter/ekk-blueprint/ekk/docs/interfaces.ru.md',
    'examples/starter/ekk-blueprint/ekk/docs/migration.ru.md',
    'examples/starter/ekk-blueprint/ekk/docs/release-evidence.ru.md',
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
    'research/agenda.md',
    'research/agenda-provenance.json',
    'research/related-work.md',
    'research/studies/method-applicability/README.md',
    'research/studies/action-readiness/README.md',
    'research/metrics-v0.3.md',
    'research/protocol-v0.1.md',
    'research/replay.py',
    'research/studies/001-environment-learning/protocol.yaml',
    'research/studies/001-environment-learning/report.md',
    'research/studies/human-shared-method-transfer/README.md',
    'research/studies/human-shared-method-transfer/harness.py',
    'research/studies/human-shared-method-transfer/protocol.yaml',
    'research/studies/human-shared-method-transfer/test_harness.py',
    'research/studies/sequence-learning/README.md',
    'research/studies/sequence-learning/protocol-hardening-0.2.yaml',
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
    'src/ekk/adapters/builtin_methods.py',
    'src/ekk/adapters/command_line.py',
    'src/ekk/adapters/contained_store.py',
    'src/ekk/adapters/context_display.py',
    'src/ekk/adapters/execution.py',
    'src/ekk/adapters/file_lock.py',
    'src/ekk/adapters/git_store.py',
    'src/ekk/adapters/local_profile.py',
    'src/ekk/adapters/markdown.py',
    'src/ekk/adapters/method_cli.py',
    'src/ekk/adapters/method_execution.py',
    'src/ekk/adapters/method_repository.py',
    'src/ekk/adapters/migration.py',
    'src/ekk/adapters/packs.py',
    'src/ekk/adapters/sqlite_index.py',
    'src/ekk/application/__init__.py',
    'src/ekk/application/experimentation.py',
    'src/ekk/application/methods.py',
    'src/ekk/application/service.py',
    'src/ekk/application/workspace.py',
    'src/ekk/application/historical_address.py',
    'src/ekk/assets.py',
    'src/ekk/capabilities.py',
    'src/ekk/cli.py',
    'src/ekk/experiments.py',
    'src/ekk/model/__init__.py',
    'src/ekk/model/experiments.py',
    'src/ekk/model/methods.py',
    'src/ekk/ports/__init__.py',
    'src/ekk/ports/methods.py',
    'src/ekk/reference_export.py',
    'tests/test_architecture_application.py',
    'tests/test_architecture_cli.py',
    'tests/test_architecture_execution.py',
    'tests/test_architecture_migration.py',
    'tests/test_architecture_profiles.py',
    'tests/test_architecture_store.py',
    'tests/test_capabilities.py',
    'tests/test_cli_entrypoint.py',
    'tests/test_pack_provider.py',
    'docs/upgrading.md',
    'tests/test_contained_store.py',
    'tests/test_context_display.py',
    'tests/test_experiments.py',
    'tests/test_markdown_cache.py',
    'tests/test_lock_contention.py',
    'tests/test_recovery_history.py',
    'tests/test_method_cli.py',
    'tests/test_method_lifecycle.py',
    'tests/test_method_transfer.py',
    'tests/test_reference_export.py',
    'tests/test_observation_compatibility.py',
    'tests/test_prepare_release.py',
    'tools/prepare_release.py',
    'docs/releasing.md',
    'docs/daily-reliability.md',
    'docs/record-queries.md',
    'docs/release-notes-0.6.md',
    'docs/release-notes-0.7.md',
    'src/ekk/adapters/backup.py',
    'src/ekk/adapters/operation_diagnostics.py',
    'src/ekk/adapters/operation_journal.py',
    'src/ekk/adapters/repository_evidence.py',
    'src/ekk/adapters/retention.py',
    'src/ekk/application/context_insights.py',
    'tests/test_backup.py',
    'tests/test_backup_cli.py',
    'tests/test_context_continuity.py',
    'tests/test_context_insights.py',
    'tests/test_operation_diagnostics.py',
    'tests/test_operation_journal.py',
    'tests/test_record_queries.py',
    'tests/test_repository_evidence.py',
    'tests/test_retention.py',
    'tests/test_workspace_entry.py',
    'tests/test_historical_address.py',
)


# Review exclusions here, never in a runtime-discovered release list.
# Each omitted test needs a concrete reason; an empty map means full coverage.
REVIEWED_TEST_EXCLUSIONS = {}
EDITION_FILE = 'release-edition.json'
EDITION_EXTRAS = ('translation-manifest.json', 'tests/test_public_english.py')


def inventory(repository):
    """Return reviewed paths, optionally using the explicit English edition data."""
    repository = Path(repository)
    declaration = repository / EDITION_FILE
    if not declaration.exists() and not declaration.is_symlink():
        return tuple(FILES)
    edition = json.loads(_source(repository, EDITION_FILE))
    if (set(edition) != {'schema', 'language', 'path_mappings', 'extra_files'}
            or edition['schema'] != 'ekk.release-edition/1'
            or edition['language'] != 'en'):
        raise ValueError('Unsupported release edition declaration')
    mappings = edition['path_mappings']
    if not isinstance(mappings, dict) or any(
            name not in FILES or '.ru.md' not in name
            or target != name.replace('.ru.md', '.md')
            for name, target in mappings.items()):
        raise ValueError('Unreviewed edition path mapping')
    extras = edition['extra_files']
    if (not isinstance(extras, list) or len(set(extras)) != len(extras)
            or any(name not in EDITION_EXTRAS for name in extras)):
        raise ValueError('Unreviewed edition extra')
    paths = tuple(mappings.get(name, name) for name in FILES) + tuple(extras) + (EDITION_FILE,)
    if len(set(paths)) != len(paths):
        raise ValueError('Colliding edition paths')
    return paths


def review_test_coverage(repository, paths):
    """Discovery is a review gate, never an addition to the public allowlist."""
    discovered = {p.relative_to(repository).as_posix()
                  for p in (repository / 'tests').rglob('test_*.py')}
    invalid = {name for name, reason in REVIEWED_TEST_EXCLUSIONS.items()
               if not isinstance(reason, str) or not reason.strip()
               or not name.startswith('tests/') or not Path(name).match('test_*.py')}
    overlap = set(paths) & set(REVIEWED_TEST_EXCLUSIONS)
    missing = discovered - set(paths) - set(REVIEWED_TEST_EXCLUSIONS)
    if invalid or overlap or missing:
        raise ValueError('Unreviewed export test coverage: ' +
                         ', '.join(sorted(invalid | overlap | missing)))
    return {name: REVIEWED_TEST_EXCLUSIONS[name]
            for name in sorted(discovered & set(REVIEWED_TEST_EXCLUSIONS))}


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
    paths = inventory(repository)
    exclusions = review_test_coverage(repository, paths)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.ekk-export-', dir=destination.parent))
    try:
        manifest = {}
        for relative in paths:
            data = _source(repository, relative)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            manifest[relative] = hashlib.sha256(data).hexdigest()
        receipt = {'schema': 'ekk.reference-export/2', 'state': 'prepared_for_review',
                   'published': False, 'license_selected': True, 'license': 'Apache-2.0',
                   'files': manifest, 'reviewed_test_exclusions': exclusions,
                   'data': 'Explicit source and synthetic starter fixtures only; no active knowledge store, local config, Git history, or runtime state.'}
        (staging / 'export-manifest.json').write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        os.rename(staging, destination)
        return receipt
    finally:
        if staging.exists():
            shutil.rmtree(staging)
