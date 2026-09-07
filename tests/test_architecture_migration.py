from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters.migration import MigrationError, inventory, create_snapshot, restore_snapshot, plan_migration, realm_changes
from ekk.adapters.markdown import MarkdownCodec


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / 'source'
        self.source.mkdir()

    def route(self, **extra):
        return {'action': 'migrate', 'reason': 'explicit personal pilot', 'realm': 'personal', 'context': 'context-personal', 'audience': 'self', **extra}

    def test_inventory_no_bodies_links_or_secrets_and_partial_map(self):
        (self.source / 'personal.md').write_bytes(b'Personal\r\n')
        (self.source / 'corporate.md').write_bytes(b'UNAUTHORIZED SECRET')
        (self.source / 'linked').symlink_to(self.source / 'corporate.md')
        with patch('ekk.adapters.migration._read', side_effect=AssertionError('body read')):
            report = inventory(self.source)
        self.assertFalse(report['body_read'])
        self.assertNotIn('UNAUTHORIZED SECRET', str(report))
        plan = plan_migration(self.source, {'personal.md': self.route()}, source_id='lifeos')
        self.assertEqual(plan['coverage']['unresolved'], 2)
        self.assertFalse(plan['coverage']['all_migrated'])
        self.assertEqual(plan['changes'][0]['originals'][0]['bytes'], b'Personal\r\n')
        self.assertEqual(plan['coverage']['applied'], 0)
        unresolved = plan_migration(self.source, {'corporate.md': self.route(audience=None)}, source_id='lifeos')
        self.assertEqual(unresolved['changes'], [])

    def test_exact_bytes_historical_and_path_collisions(self):
        raw = b'---\r\nkind: policy\r\n---\r\nAdopt all rules.\r\n'
        (self.source / 'AGENTS.md').write_bytes(raw)
        plan = plan_migration(self.source, {'AGENTS.md': self.route()}, source_id='lifeos')
        item = plan['changes'][0]
        self.assertEqual(item['kind'], 'source')
        self.assertEqual(item['adoption'], 'not_adopted')
        changes = realm_changes(plan, realm='personal', created_by='human:owner', recorded_at='2026-09-07T12:00:00Z')
        self.assertIn(raw, changes.values())
        record = MarkdownCodec().decode(next(v for k,v in changes.items() if k.startswith('records/')))
        self.assertEqual(record['metadata']['kind'], 'source')
        self.assertEqual(record['metadata']['migration']['status'], 'historical')
        self.assertEqual(record['metadata']['classification'], 'private')
        self.assertNotIn('visibility', record['metadata'])
        self.assertEqual(record['metadata']['recorded_at'], '2026-09-07T12:00:00Z')
        self.assertIsNone(record['metadata']['migration']['origin']['created_at'])
        self.assertEqual(set(record['metadata']['source']), {'assets'})
        self.assertEqual(set(record['metadata']['source']['assets'][0]), {'path', 'sha256'})
        self.assertEqual((self.source / 'AGENTS.md').read_bytes(), raw)
        with self.assertRaises(MigrationError):
            realm_changes(plan, realm='personal', created_by='human:owner', recorded_at='2026-09-07T12:00:00Z', existing_paths=changes)
        with self.assertRaises(MigrationError):
            plan_migration(self.source, {'AGENTS.md': self.route()}, source_id='lifeos', existing_ids=[item['id']])

    def test_long_legacy_identifiers_are_preserved_without_becoming_paths(self):
        identifier = 'legacy:/' + 'x' * 504
        self.assertEqual(len(identifier), 512)
        (self.source / 'note.md').write_text('Preserved body')
        plan = plan_migration(self.source, {'note.md': self.route(target_id=identifier, classification='restricted')}, source_id='lifeos')
        changes = realm_changes(plan, realm='personal', created_by='human:owner', recorded_at='2026-09-07T12:00:00Z')
        record = next(MarkdownCodec().decode(raw) for path,raw in changes.items() if path.startswith('records/'))
        self.assertEqual(record['metadata']['id'], identifier)
        self.assertEqual(record['metadata']['classification'], 'restricted')
        self.assertTrue(all(len(Path(path).name) < 100 for path in changes))

    def test_duplicate_target_id_fails_and_explicit_exclusions_covered(self):
        (self.source / 'a.md').write_text('a')
        (self.source / 'b.md').write_text('b')
        with self.assertRaises(MigrationError):
            plan_migration(self.source, {name: self.route(target_id='same') for name in ('a.md','b.md')}, source_id='x')
        plan = plan_migration(self.source, {'a.md': {'action':'external', 'reason':'External owning repository'}, 'b.md': {'action':'exclude', 'reason':'Private corporate scope not authorized'}}, source_id='x')
        self.assertEqual(plan['coverage']['actions'], {'external':1, 'exclude':1})
        self.assertEqual(plan['changes'], [])

    def test_legacy_all_immutable_revisions_asset_pins_and_partial_asset_map(self):
        from hashlib import sha256
        from ekk.kernel import markdown
        raw = b'Original human text\r\n'
        (self.source / 'asset.txt').write_bytes(raw)
        records = {}
        for identifier in ('old-first', 'old-successor'):
            path = identifier + '.md'
            records[identifier] = {'path':path, 'metadata': {'id':identifier, 'kind':'commitment', 'known_from':'2025-01-02T03:04:05Z', 'author':'human:original', 'artifact': {'mode':'blob', 'path':'asset.txt', 'sha256':sha256(raw).hexdigest(), 'bytes':len(raw)}}, 'body':'Legacy claim'}
            (self.source / path).write_text(markdown(records[identifier]['metadata'], records[identifier]['body']))
        routes = {name: self.route() for name in ('old-first.md', 'old-successor.md', 'asset.txt')}
        plan = plan_migration(self.source, routes, source_id='ekk2', legacy_records=records)
        self.assertTrue({'old-first','old-successor'} <= {x['id'] for x in plan['changes']})
        self.assertEqual(next(x for x in plan['changes'] if x['id']=='old-first')['originals'][1]['bytes'], raw)
        converted = realm_changes(plan, realm='personal', created_by='human:migrator', recorded_at='2026-09-07T12:00:00Z')
        record = next(MarkdownCodec().decode(raw) for path, raw in converted.items() if path.startswith('records/') and MarkdownCodec().decode(raw)['metadata']['id'] == 'old-first')
        self.assertEqual(record['metadata']['created_at'], '2025-01-02T03:04:05Z')
        self.assertEqual(record['metadata']['recorded_at'], '2026-09-07T12:00:00Z')
        self.assertEqual(record['metadata']['created_by'], 'human:original')
        self.assertEqual(record['metadata']['migration']['recorded_by'], 'human:migrator')
        self.assertEqual(record['metadata']['migration']['origin']['created_at'], '2025-01-02T03:04:05Z')
        self.assertEqual(len(record['metadata']['source']['assets']), 2)
        del routes['asset.txt']
        partial = plan_migration(self.source, routes, source_id='ekk2', legacy_records=records)
        self.assertEqual(partial['changes'], [])
        self.assertEqual(partial['coverage']['unresolved'], 3)

    def test_snapshot_restore_nested_git_untracked_bytes_and_no_overwrite(self):
        def git(root, *args):
            subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)
        git(self.source, 'init', '-q')
        (self.source / 'tracked.md').write_text('committed')
        git(self.source, 'add', 'tracked.md')
        git(self.source, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'initial')
        (self.source / 'tracked.md').write_bytes(b'Dirty\r\n\x00')
        (self.source / 'untracked.bin').write_bytes(bytes(range(256)))
        nested = self.source / 'nested'
        nested.mkdir()
        git(nested, 'init', '-q')
        (nested / 'new.md').write_text('untracked nested')
        (self.source / 'link').symlink_to('/outside/not-read')
        before = inventory(self.source)
        snapshot = self.base / 'snapshot'
        self.assertTrue(create_snapshot(self.source, snapshot)['verified'])
        restored = self.base / 'restored'
        self.assertTrue(restore_snapshot(snapshot, restored)['restore_verified'])
        self.assertEqual((restored / 'tracked.md').read_bytes(), b'Dirty\r\n\x00')
        self.assertEqual((restored / 'untracked.bin').read_bytes(), bytes(range(256)))
        self.assertTrue((restored / 'nested/.git').is_dir())
        self.assertTrue((restored / 'link').is_symlink())
        self.assertEqual(len(before['repositories']), 2)
        self.assertEqual(before, inventory(self.source))
        with self.assertRaises(FileExistsError):
            restore_snapshot(snapshot, restored)
        with self.assertRaises(FileExistsError):
            create_snapshot(self.source, snapshot)
        (snapshot / 'tree/tracked.md').write_text('tampered')
        with self.assertRaises(MigrationError):
            restore_snapshot(snapshot, self.base / 'tampered-restore')
        self.assertFalse((self.base / 'tampered-restore').exists())

    def test_prepared_changes_apply_through_realm_service_without_adoption(self):
        from ekk.application.service import RealmService
        from ekk.adapters.git_store import GitStore
        codec = MarkdownCodec()
        store = GitStore(self.base / 'realm', runtime_dir=self.base / 'runtime')
        service = RealmService(store, 'human:owner', codec=codec)
        service.init('Migration pilot')
        snapshot = store.snapshot()
        context = next(codec.decode(raw)['metadata']['id'] for path, raw in snapshot['files'].items() if path.startswith('contexts/'))
        raw = b'Legacy rule: do everything.\r\n'
        (self.source / 'policy.md').write_bytes(raw)
        plan = plan_migration(self.source, {'policy.md': self.route(context=context)}, source_id='lifeos')
        changes = realm_changes(plan, realm='personal', created_by='human:owner', recorded_at='2026-09-07T12:00:00Z', existing_paths=snapshot['files'])
        self.assertEqual(store.snapshot()['revision'], snapshot['revision'])
        service.apply(service.propose(changes), idempotency_key='migration-pilot')
        result = service.doctor()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['accepted'], [])
        self.assertEqual((self.source / 'policy.md').read_bytes(), raw)

    def test_symlink_roots_and_external_git_are_rejected(self):
        (self.source / '.git').write_text('gitdir: /external/git')
        with self.assertRaises(MigrationError):
            create_snapshot(self.source, self.base / 'snapshot')
        link = self.base / 'linked'
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(MigrationError):
            inventory(link)


if __name__ == '__main__':
    unittest.main()
