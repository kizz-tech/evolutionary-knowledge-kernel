"""Full backup authority and offline isolated recovery through the registered CLI."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ekk.adapters.command_line import dispatch, parser, service


class BackupCliTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        env=patch.dict(os.environ,{'EKK_CONFIG_HOME':str(self.root/'config'),
            'EKK_DATA_HOME':str(self.root/'data'),'EKK_CACHE_HOME':str(self.root/'cache')})
        env.start(); self.addCleanup(env.stop)
        self.app=service(self.root/'realm')
        from ekk.adapters.packs import PackDirectory
        from ekk.assets import pack_directory
        installed=PackDirectory(pack_directory())
        self.app.init('Backup owner',realm_id=self.app.initial_realm_id,context_id='scope',
                      packs=[installed.pin('ekk/base'), installed.pin('ekk/research')])
        self.profiles=self.root/'config/profiles'; self.profiles.mkdir(parents=True)
        self.profile={'schema':'ekk.profile/0.1','uid':os.getuid(),
            'realms':{'owned':{'path':str(self.root/'realm'),'id':self.app.initial_realm_id}}}
        (self.profiles/'test.yaml').write_text(json.dumps(self.profile))

    def call(self, op, *args, request=None):
        return dispatch(parser().parse_args([op,*args]),request or {})

    def test_scope_root_and_default_profile_cannot_expand_to_backup(self):
        destination=self.root/'forbidden.tar'
        for args in ([ '--root',str(self.root/'realm')],
                     [ '--realm','owned'],
                     [ '--profile','test','--realm','owned','--scope','scope']):
            with self.assertRaises(PermissionError):
                self.call('backup',*args,'--destination',str(destination))
            self.assertFalse(destination.exists())
        snapshot=self.app.store.snapshot()
        policy=self.app.codec.load_yaml(snapshot['files']['.ekk/governance.yaml'])
        policy['version']+=1
        policy['grants'][0]['scopes']=['scope']
        self.app.configure({'.ekk/governance.yaml':self.app.codec.dump_yaml(policy)},
                           base=snapshot['revision'],idempotency_key='narrow-owner')
        with self.assertRaises(PermissionError):
            self.call('backup','--profile','test','--realm','owned','--destination',str(destination))
        self.assertFalse(destination.exists())

    def test_registered_backup_and_offline_restore_keep_the_original_route(self):
        archive=self.root/'backup.tar'
        backup=self.call('backup','--profile','test','--realm','owned','--destination',str(archive))
        self.assertEqual('realm',backup['backup_scope'])
        self.app.store.path.rename(self.root/'offline-source')
        before=(self.profiles/'test.yaml').read_bytes()
        restored=self.call('restore','--profile','test','--realm','owned','--file',str(archive),
            '--destination',str(self.root/'copy'),'--restore-data-home',str(self.root/'copy-data'),
            '--sha256',backup['sha256'])
        self.assertEqual('validated',restored['state'])
        self.assertEqual('not_performed',restored['production_cutover'])
        self.assertEqual(before,(self.profiles/'test.yaml').read_bytes())
        self.assertFalse((self.root/'realm').exists())
        self.profile['realms']['owned']['id']='realm:wrong'
        (self.profiles/'test.yaml').write_text(json.dumps(self.profile))
        with self.assertRaises(PermissionError):
            self.call('restore','--profile','test','--realm','owned','--file',str(archive),
                '--destination',str(self.root/'wrong-copy'),'--restore-data-home',str(self.root/'wrong-data'))
        self.assertFalse((self.root/'wrong-copy').exists())
        self.assertFalse((self.root/'wrong-data').exists())


if __name__=='__main__': unittest.main()
