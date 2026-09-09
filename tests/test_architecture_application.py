import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ekk.adapters.git_store import GitStore
from ekk.adapters.markdown import MarkdownCodec
from ekk.application import RealmService
from ekk.model import Conflict, IdempotencyConflict, digest

class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=GitStore(Path(self.tmp.name)/'realm',Path(self.tmp.name)/'runtime')
        self.codec=MarkdownCodec();self.app=RealmService(self.store,'owner',lambda:'2026-09-07T12:00:00Z',codec=self.codec)
        self.app.init('Synthetic realm',context_id='scope')

    def add(self, metadata, body='', accept=()):
        proposal=self.app.propose({f"records/{metadata['id']}.md":self.codec.encode(metadata,body)})
        return self.app.apply(proposal,idempotency_key=metadata['id']+'-'+str(metadata['revision']),accept=accept)

    def meta(self,key,kind='note',**extra):
        return dict(**({'context':{'purpose':key}} if kind=='context' else {}),schema='ekk.record/0.1',id=key,title=key,kind=kind,scope=['scope'],revision=1,created_at='2026-09-07T10:00:00Z',created_by='owner',**extra)

    def source(self):
        proposal=self.app.capture(b'\x00 exact\r\n bytes\xff',title='source',scope=['scope'])
        self.app.apply(proposal,idempotency_key='capture')
        records=self.app._load(self.store.snapshot())[-1]
        return next(r for r in records.values() if r['metadata']['kind']=='source')

    def decision(self,key='decision',**extra):
        r=self.source()
        return self.meta(key,'policy',basis=[{'id':r['metadata']['id'],'digest':'sha256:'+r['digest'],'snapshot':self.store.snapshot()['revision']}],commitment={'expectation':'No data loss'},**extra)

    def test_source_exact_and_immutable(self):
        r=self.source(); p=r['metadata']['source']['assets'][0]['path']
        self.assertEqual(self.store.snapshot()['files'][p],b'\x00 exact\r\n bytes\xff')
        with self.assertRaises(ValueError):self.app.apply(self.app.propose({p:b'changed'}),idempotency_key='tamper')
        self.assertTrue(self.app.doctor()['ok'])

    def test_forged_status_is_not_adoption_and_revision_needs_acceptance(self):
        m=self.decision(accepted=True); self.add(m)
        self.assertFalse(any(r['governs'] for r in self.app.context(['scope'])['records']))
        self.app.apply(self.app.propose({}),idempotency_key='accept',accept=['decision'])
        self.assertTrue(any(r['governs'] for r in self.app.context(['scope'])['records']))
        m['revision']=2;self.add(m,'new body')
        self.assertFalse(any(r['governs'] for r in self.app.context(['scope'])['records']))

    def test_mandatory_constraints_block_budget_without_silent_truncation(self):
        m=self.decision();self.add(m,'mandatory words '*100,accept=['decision'])
        result=self.app.context(['scope'],'unrelated task',budget=10)
        self.assertTrue(result['blocked']);self.assertTrue(result['manifest']['incomplete'])
        full=self.app.context(['scope'],'unrelated task')
        self.assertFalse(full['blocked']);self.assertIn('decision',[r['id'] for r in full['records']])
        self.assertEqual(len(full['manifest']['used_refs']),len(full['records']))

    def test_current_policy_denies_unauthorized_accept_and_forged_export(self):
        m=self.decision();self.add(m)
        other=RealmService(self.store,'attacker',codec=self.codec)
        with self.assertRaises(PermissionError):other.apply(other.propose({}),idempotency_key='attack',accept=['decision'])
        with self.assertRaises(PermissionError):self.app.export(['decision'],destination='public',grants=[{'id':'forged','principal':'owner','ids':['decision'],'declassify':True}])
        with self.assertRaises(PermissionError):self.app.propose({'.ekk/governance.yaml':b'bad'})

    def test_unknown_kind_inert_unknown_mandatory_fails(self):
        self.add(self.meta('unknown','alien',accepted=True,commitment={'expectation':'anything'}))
        r=next(r for r in self.app.context(['scope'])['records'] if r['id']=='unknown')
        self.assertTrue(r['inert']);self.assertFalse(r['governs'])
        with self.assertRaises(ValueError):self.add(self.meta('unsupported',required_semantics=['future']))

    def test_registered_review_triggers_only(self):
        m=self.decision(valid_until='2026-09-06T12:00:00Z',review={'triggers':['expired','when situation changes']})
        self.add(m,accept=['decision']);result=self.app.review(['scope'])
        self.assertEqual(result['candidates'][0]['detector'],'expired')
        self.assertEqual(len(result['unregistered_conditions']),1);self.assertEqual(result['mutations'],0)

    def test_assurance_dimensions_are_independent(self):
        evidence=self.meta('evidence','observation',observation={'subject':'scope','observed_at':'2026-09-07T10:00:00Z','aspects':['build']})
        self.add(evidence,'synthetic evidence')
        pinned={'id':'evidence','revision':1}
        m=self.decision(assurance={
            'evidence':{'status':'supported','basis':[pinned]},
            'implementation':{'status':'verified','basis':[pinned]},
        })
        self.add(m,accept=['decision'])
        item=self.app.assurance(['scope'])['items'][0]
        self.assertEqual(item['owner_authorized']['status'],'accepted')
        self.assertEqual(item['evidence_supported']['status'],'supported')
        self.assertEqual(item['implementation_verified']['status'],'verified')
        self.assertEqual(item['observed_benefit']['status'],'unknown')

    def test_acceptance_alone_does_not_claim_evidence_or_benefit(self):
        self.add(self.decision(),accept=['decision'])
        item=self.app.assurance(['scope'])['items'][0]
        self.assertEqual(item['owner_authorized']['status'],'accepted')
        self.assertEqual(item['evidence_supported']['status'],'unknown')
        self.assertEqual(item['implementation_verified']['status'],'not_run')
        self.assertEqual(item['observed_benefit']['status'],'unknown')

    def test_observation_gap_reports_missing_and_stale_aspects(self):
        m=self.decision(review={'triggers':[{'detector':'observation_gap','aspects':['quality','regressions'],'max_age_days':2}]})
        self.add(m,accept=['decision'])
        old=self.meta('old-observation','observation',basis=m['basis'],observation={'subject':'decision','observed_at':'2026-09-01T10:00:00Z','aspects':['quality']})
        self.add(old)
        candidate=self.app.review(['scope'])['candidates'][0]
        self.assertEqual(candidate['detector'],'observation_gap')
        self.assertIn('unobserved aspects: regressions',candidate['reasons'])
        self.assertIn('stale observations: quality',candidate['reasons'])

    def test_recent_complete_observation_avoids_gap_candidate(self):
        m=self.decision(review={'triggers':[{'detector':'observation_gap','aspects':['quality'],'max_age_days':2}]})
        self.add(m,accept=['decision'])
        observed=self.meta('recent-observation','observation',basis=m['basis'],observation={'subject':'decision','observed_at':'2026-09-07T10:00:00Z','aspects':['quality']})
        self.add(observed)
        self.assertEqual(self.app.review(['scope'])['candidates'],[])

    def test_local_evolution_cannot_expand_and_explicit_needs_basis(self):
        local=self.decision(evolution={'propagation':'local','origin_scopes':['other'],'applicability':'same component','rollback':'supersede this rule'})
        with self.assertRaises(ValueError):self.add(local)
        explicit={**local,'evolution':{'propagation':'explicit','origin_scopes':['scope'],'applicability':'named targets','rollback':'supersede this rule'}}
        with self.assertRaises(ValueError):self.add(explicit)

    def test_method_contract_requires_stops_and_autonomy_boundary(self):
        incomplete=self.meta('method-record',method={'supported_work':['review'],'guaranteed_result':['report'],'checks':['schema'],'assumptions':['visible inputs']})
        with self.assertRaises(ValueError):self.add(incomplete)

    def test_markdown_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):self.codec.decode(b'---\nid: a\nid: b\n---\n')

    def test_acceptance_retry_is_idempotent(self):
        m=self.decision();proposal=self.app.propose({'records/decision.md':self.codec.encode(m)})
        first=self.app.apply(proposal,idempotency_key='retry',accept=['decision'])
        second=self.app.apply(proposal,idempotency_key='retry',accept=['decision'])
        self.assertEqual(first,second)

    def test_historical_basis_keeps_old_bytes_and_triggers_review(self):
        basis=self.meta('basis');self.add(basis,'old evidence')
        snap=self.store.snapshot(); old=self.app._load(snap)[-1]['basis']
        decision=self.meta('historical','decision',basis=[{'id':'basis','digest':'sha256:'+old['digest'],'snapshot':snap['revision']}],commitment={'expectation':'works'},review={'triggers':['changed_basis']})
        self.add(decision,accept=['historical'])
        basis['revision']=2;self.add(basis,'new evidence')
        self.assertTrue(self.app.doctor()['ok'])
        context=self.app.context(['scope'],'historical')
        self.assertIn('old evidence',[r['body'] for r in context['records']])
        self.assertEqual(self.app.review(['scope'])['candidates'][0]['detector'],'changed_basis')

    def test_export_uses_policy_allowlist_and_preserves_classification(self):
        self.add(self.meta('share'),'authorized synthetic content')
        snap=self.store.snapshot();policy=self.codec.load_yaml(snap['files']['.ekk/governance.yaml'])
        policy['version']=2;policy['export_grants']=[{'id':'grant','principal':'owner','destination':'other-private','ids':['share'],'source_visibility':'private','destination_visibility':'private'}]
        self.store.apply({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='policy',principal='owner',policy_digest=digest(snap['files']['.ekk/governance.yaml']))
        bundle=self.app.export(['share'],destination='other-private',grants=['grant'])
        self.assertEqual(bundle['records'][0]['classification'],'private')
        self.assertEqual(len(bundle['files']),1)
        with self.assertRaises(PermissionError):self.app.export(['share'],destination='public',grants=['grant'])

    def test_orphan_blob_does_not_bypass_write_authority(self):
        other=RealmService(self.store,'attacker',codec=self.codec)
        with self.assertRaises(PermissionError):other.apply(other.propose({'sources/orphan':b'payload'}),idempotency_key='orphan')

    def test_pack_missing_payload_fails_closed(self):
        snap=self.store.snapshot()
        with self.assertRaises(ValueError):
            self.app.configure({'.ekk/packs.lock.yaml':self.codec.dump_yaml({'schema':'ekk.packs-lock/0.1','packages':[{'id':'ekk/base','version':'0.1','origin':'pack:ekk/base','sha256':'0'*64}]})},base=snap['revision'],idempotency_key='badpack')

    def test_configuration_requires_owner_and_next_policy_version(self):
        snap=self.store.snapshot();policy=self.codec.load_yaml(snap['files']['.ekk/governance.yaml'])
        with self.assertRaises(ValueError):self.app.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='badversion')
        policy['version']=2
        other=RealmService(self.store,'attacker',codec=self.codec)
        with self.assertRaises(PermissionError):other.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='owner')
        self.app.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='goodversion')
        self.assertTrue(self.app.doctor()['ok'])

    def test_relation_dependency_and_explicit_context_basis(self):
        basis=self.meta('linked');self.add(basis,'supporting material')
        self.add(self.meta('derived',relations=[{'rel':'derived_from','target':'linked','revision':1}]),'uniquetask')
        result=self.app.context(['scope'],'uniquetask')
        self.assertIn('linked',[r['id'] for r in result['records']])
        snap=self.store.snapshot();context=self.app._load(snap)[-1]['scope']['metadata']
        context['revision']=2;context['context']['basis']=['derived']
        self.app.apply(self.app.propose({'contexts/scope.md':self.codec.encode(context)}),idempotency_key='declare')
        self.assertTrue(self.app.context(['scope'])['blocked'])

    def test_write_only_cannot_withdraw_accepted_constraint(self):
        m=self.decision();self.add(m,accept=['decision'])
        snap=self.store.snapshot();policy=self.codec.load_yaml(snap['files']['.ekk/governance.yaml']);policy['version']=2
        policy['grants'].append({'principal':'writer','actions':['read','write'],'scopes':['scope']})
        self.app.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='writergrant')
        writer=RealmService(self.store,'writer',codec=self.codec)
        m['revision']=2
        for changes in ({'records/decision.md':self.codec.encode(m,'edited')},{'records/decision.md':None}):
            with self.assertRaises(PermissionError):writer.apply(writer.propose(changes),idempotency_key='withdraw')

    def test_scoped_read_does_not_leak_multiscope_or_private_reference(self):
        private=self.meta('private','context');private['scope']=['private'];self.add(private)
        self.add(self.meta('mixed',depends_on=['private']),'sensitive link')
        mult=self.meta('multiscope');mult['scope']=['scope','private'];self.add(mult)
        snap=self.store.snapshot();policy=self.codec.load_yaml(snap['files']['.ekk/governance.yaml']);policy['version']=2
        policy['grants'].append({'principal':'reader','actions':['read'],'scopes':['scope']})
        self.app.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='readergrant')
        reader=RealmService(self.store,'reader',codec=self.codec)
        result=reader.context(['scope']);serialized=json.dumps(result)
        self.assertNotIn('multiscope',serialized);self.assertNotIn('sensitive link',serialized)
        self.assertNotIn('mixed',serialized)

    def test_starter_fixture_reads_without_rewriting(self):
        fixture=Path(__file__).resolve().parents[1]/'examples/starter/ekk-blueprint/ekk/knowledge'
        files={p.relative_to(fixture).as_posix():p.read_bytes() for p in fixture.rglob('*') if p.is_file()}
        store=GitStore(Path(self.tmp.name)/'starter',Path(self.tmp.name)/'starter-runtime')
        store.initialize(files)
        app=RealmService(store,'principal:example-owner',codec=self.codec)
        self.assertTrue(app.doctor()['ok'])
        realm=self.codec.load_yaml(files['.ekk/realm.yaml'])
        context=app.context([realm['default_context']])
        self.assertEqual(len(context['records']),4)
        self.assertFalse(any(r['governs'] for r in context['records']))
        self.assertEqual(files,store.snapshot()['files'])

    def test_digest_only_historical_basis_resolves(self):
        basis=self.meta('history-basis');self.add(basis,'original')
        old=self.app._load(self.store.snapshot())[-1]['history-basis']
        decision=self.meta('history-decision','decision',relations=[{'rel':'derived_from','target':'history-basis','digest':'sha256:'+old['digest']}])
        self.add(decision,'Expected: preserve the original evidence.',accept=['history-decision'])
        basis['revision']=2;self.add(basis,'changed')
        self.assertTrue(self.app.doctor()['ok'])
        self.assertIn('original',[r['body'] for r in self.app.context(['scope'],'history-decision')['records']])

    def test_write_only_cannot_change_context_constraint_declaration(self):
        m=self.decision();self.add(m,accept=['decision'])
        context=self.app._load(self.store.snapshot())[-1]['scope']['metadata'];context['revision']=2;context['context']['basis']=['decision']
        self.app.apply(self.app.propose({'contexts/scope.md':self.codec.encode(context)}),idempotency_key='declare-policy')
        snap=self.store.snapshot();policy=self.codec.load_yaml(snap['files']['.ekk/governance.yaml']);policy['version']=2
        policy['grants'].append({'principal':'writer','actions':['write'],'scopes':['scope']})
        self.app.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='scope-writer')
        writer=RealmService(self.store,'writer',codec=self.codec);context['revision']=3;context['context']['basis']=[]
        with self.assertRaises(PermissionError):writer.apply(writer.propose({'contexts/scope.md':self.codec.encode(context)}),idempotency_key='remove-declaration')

    def test_supersedes_pins_exact_revision_not_future_revision(self):
        basis=self.meta('replacement-basis');self.add(basis)
        first=self.meta('first-decision','decision',relations=[{'rel':'derived_from','target':'replacement-basis','revision':1}])
        self.add(first,accept=['first-decision'])
        successor=self.meta('successor','decision',relations=[{'rel':'derived_from','target':'replacement-basis','revision':1},{'rel':'supersedes','target':'first-decision','revision':1}])
        self.add(successor,accept=['successor'])
        first['revision']=2;self.add(first,'new choice',accept=['first-decision'])
        governing={r['id'] for r in self.app.context(['scope'])['records'] if r['governs']}
        self.assertEqual(governing,{'first-decision','successor'})

    def test_retry_after_later_revision_returns_original_receipt(self):
        m=self.meta('retry-note');proposal=self.app.propose({'records/retry-note.md':self.codec.encode(m)})
        first=self.app.apply(proposal,idempotency_key='original-request')
        m['revision']=2;self.add(m,'later body')
        self.assertEqual(first,self.app.apply(proposal,idempotency_key='original-request'))
        self.assertEqual(self.app._load(self.store.snapshot())[-1]['retry-note']['body'],'later body')

    def test_unpublished_stale_base_stops_before_history_scan_and_store_apply(self):
        proposal=self.app.propose({'records/new.md':self.codec.encode(self.meta('new'))})
        self.add(self.meta('competing'))
        with patch.object(self.store,'history',wraps=self.store.history) as history, patch.object(self.store,'apply',wraps=self.store.apply) as apply:
            with self.assertRaises(Conflict):self.app.apply(proposal,idempotency_key='stale-new')
            apply.assert_not_called()
            # One history read selects the original base's alias mode. The
            # all-history recreated-ID scan and its per-snapshot loads never run.
            self.assertEqual(1,history.call_count)

    def test_stale_changed_key_is_rejected_before_stale_error(self):
        metadata=self.meta('exact-key')
        proposal=self.app.propose({'records/exact-key.md':self.codec.encode(metadata,'original')})
        receipt=self.app.apply(proposal,idempotency_key='exact-key')
        self.add(self.meta('later'))
        changed=self.app.propose({'records/exact-key.md':self.codec.encode(metadata,'different')},base=proposal['base'])
        with self.assertRaises(IdempotencyConflict):self.app.apply(changed,idempotency_key='exact-key')
        self.assertEqual(receipt,self.app.apply(proposal,idempotency_key='exact-key'))

    def test_current_write_revocation_precedes_stale_lookup(self):
        proposal=self.app.propose({'records/new.md':self.codec.encode(self.meta('new'))})
        snapshot=self.store.snapshot();policy=self.codec.load_yaml(snapshot['files']['.ekk/governance.yaml'])
        policy['version']+=1;policy['grants'][0]['actions'].remove('write')
        self.app.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snapshot['revision'],idempotency_key='revoke-write')
        with patch.object(self.store,'lookup',wraps=self.store.lookup) as lookup:
            with self.assertRaises(PermissionError):self.app.apply(proposal,idempotency_key='stale-denied')
            lookup.assert_not_called()

    def test_exact_pack_artifact_inventory_is_verified(self):
        fixture=Path(__file__).resolve().parents[1]/'examples/starter/ekk-blueprint/ekk/packs/base'
        payload={p.relative_to(fixture).as_posix():p.read_bytes() for p in fixture.rglob('*') if p.is_file()}
        sha=digest(json.dumps({p:digest(raw) for p,raw in payload.items()},sort_keys=True,separators=(',',':')).encode())
        app=RealmService(self.store,'owner',codec=self.codec,pack_loader=lambda _id,_version:payload)
        snap=self.store.snapshot();lock={'schema':'ekk.packs-lock/0.1','packages':[{'id':'ekk/base','version':'0.1.0-design.en','origin':'pack:ekk/base','sha256':sha}]}
        app.configure({'.ekk/packs.lock.yaml':self.codec.dump_yaml(lock)},base=snap['revision'],idempotency_key='exact-pack')
        self.assertTrue(app.doctor()['ok'])
        payload['METHOD.md']+=b'\nchanged'
        self.assertFalse(app.doctor()['ok'])

    def test_external_refs_are_unverified_and_do_not_expand_lookup(self):
        self.add(self.meta('foreign-ref',relations=[{'rel':'about','target':'foreign-private-record','realm':'foreign-realm','revision':1}]))
        self.assertEqual(self.app.doctor()['unverified'][0]['id'],'foreign-ref')
        result=self.app.context(['scope'],'foreign-ref')
        self.assertTrue(result['blocked']);self.assertIn('external reference unverified; no cross-realm lookup performed',result['unknowns'])

    def test_unreadable_accepted_decision_basis_blocks_without_disclosure(self):
        private=self.meta('private','context');private['scope']=['private'];self.add(private)
        secret=self.meta('secret-basis');secret['scope']=['private'];self.add(secret,'hidden substance')
        record=self.app._load(self.store.snapshot())[-1]['secret-basis']
        choice=self.meta('sensitive-choice','decision',relations=[{'rel':'derived_from','target':'secret-basis','digest':'sha256:'+record['digest']}])
        self.add(choice,'hidden choice',accept=['sensitive-choice'])
        snap=self.store.snapshot();policy=self.codec.load_yaml(snap['files']['.ekk/governance.yaml']);policy['version']=2
        policy['grants'].append({'principal':'reader','actions':['read'],'scopes':['scope']})
        self.app.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='hidden-basis-reader')
        reader=RealmService(self.store,'reader',codec=self.codec);result=reader.context(['scope'])
        self.assertTrue(result['blocked']);self.assertTrue(result['manifest']['incomplete'])
        self.assertIn('applicable accepted commitment or basis outside authorized projection',result['unknowns'])
        rendered=json.dumps(result)
        for secret in ('secret-basis','sensitive-choice','hidden substance','hidden choice'):self.assertNotIn(secret,rendered)

    def test_foreign_reference_never_aliases_local_id(self):
        self.add(self.meta('collision'))
        local=self.app._load(self.store.snapshot())[-1]['collision']
        choice=self.meta('foreign-choice','decision',basis=[{'id':'collision','realm':'other-realm','revision':1,'digest':'sha256:'+local['digest']}])
        with self.assertRaises(ValueError):self.add(choice,accept=['foreign-choice'])
        self.add(choice)
        self.assertTrue(self.app.context(['scope'],'foreign-choice')['blocked'])

    def test_deleted_revision_cannot_be_reused_or_reactivate_acceptance(self):
        basis=self.meta('versioned');self.add(basis,'original basis')
        decision=self.meta('revision-choice','decision',relations=[{'rel':'derived_from','target':'versioned','revision':1}]);self.add(decision,accept=['revision-choice'])
        self.app.apply(self.app.propose({'records/versioned.md':None}),idempotency_key='delete-basis')
        with self.assertRaises(ValueError):self.add(basis,'replacement with reused revision')
        basis['revision']=2;self.add(basis,'new revision')
        context=self.app.context(['scope'],'revision-choice')
        self.assertIn('original basis',[r['body'] for r in context['records']])
        raw=self.store.snapshot()['files']['records/revision-choice.md']
        self.app.apply(self.app.propose({'records/revision-choice.md':None}),idempotency_key='withdraw-choice')
        with self.assertRaises(ValueError):self.app.apply(self.app.propose({'records/revision-choice.md':raw}),idempotency_key='reactivate-old')

    def test_workspace_cap_blocks_other_scope_and_orphan_assets(self):
        other=self.meta('other-scope','context');other['scope']=['other-scope'];self.add(other)
        bounded=RealmService(self.store,'owner',codec=self.codec,allowed_scopes=['scope'])
        record=self.meta('outside');record['scope']=['other-scope']
        with self.assertRaises(PermissionError):bounded.apply(bounded.propose({'records/outside.md':self.codec.encode(record)}),idempotency_key='outside-binding')
        with self.assertRaises(PermissionError):bounded.apply(bounded.propose({'sources/orphan.bin':b'orphan'}),idempotency_key='owner-orphan')
        self.assertEqual(bounded.doctor()['records'],1)

    def test_historical_conflict_does_not_block_new_target_revision(self):
        self.add(self.meta('conflict-basis'))
        target=self.meta('conflict-target','decision',relations=[{'rel':'derived_from','target':'conflict-basis','revision':1}]);self.add(target,accept=['conflict-target'])
        other=self.meta('conflict-other','decision',relations=[{'rel':'derived_from','target':'conflict-basis','revision':1},{'rel':'contradicts','target':'conflict-target','revision':1}]);self.add(other,accept=['conflict-other'])
        self.assertTrue(self.app.context(['scope'])['blocked'])
        target['revision']=2;self.add(target,'updated',accept=['conflict-target'])
        self.assertFalse(self.app.context(['scope'])['blocked'])

    def test_review_hidden_basis_has_only_generic_unknown(self):
        private=self.meta('private','context');private['scope']=['private'];self.add(private)
        basis=self.meta('review-secret');basis['scope']=['private'];self.add(basis,'original')
        decision=self.meta('review-choice','decision',relations=[{'rel':'derived_from','target':'review-secret','revision':1}],review={'triggers':['changed_basis']});self.add(decision,accept=['review-choice'])
        basis['revision']=2;self.add(basis,'changed')
        snap=self.store.snapshot();policy=self.codec.load_yaml(snap['files']['.ekk/governance.yaml']);policy['version']=2;policy['grants'].append({'principal':'reader','actions':['read'],'scopes':['scope']})
        self.app.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='review-reader')
        result=RealmService(self.store,'reader',codec=self.codec).review(['scope'])
        self.assertTrue(result['incomplete']);self.assertEqual(result['candidates'],[])
        self.assertNotIn('review-choice',json.dumps(result));self.assertNotIn('review-secret',json.dumps(result))

    def test_malformed_grant_sequences_fail_closed(self):
        snapshot=self.store.snapshot();policy=self.codec.load_yaml(snapshot['files']['.ekk/governance.yaml'])
        policy['version']=2;policy['grants']=[{'principal':'attacker','actions':'readwriteaccept','scopes':'*'}]
        with self.assertRaises(ValueError):self.app.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snapshot['revision'],idempotency_key='bad-grant')
        self.assertEqual(self.store.snapshot()['revision'],snapshot['revision'])

    def test_foreign_declared_basis_returns_blocked_unknown(self):
        snap=self.store.snapshot();records=self.app._load(snap)[-1];r=records['scope'];m=r['metadata'];m['revision']+=1
        m['context']['basis']=[{'target':'foreign-record','realm':'foreign-realm','revision':1}]
        self.app.apply(self.app.propose({r['path']:self.codec.encode(m,r['body'])}),idempotency_key='external-declaration')
        result=self.app.context(['scope'])
        self.assertTrue(result['blocked']);self.assertTrue(result['unknowns'])

    def test_runtime_realm_matches_exact_schema_types(self):
        snap=self.store.snapshot();realm=self.codec.load_yaml(snap['files']['.ekk/realm.yaml'])
        for field,value in (('id','x'),('name',7),('owner',8),('storage',{'record_roots':['records','records'],'source_root':'sources','receipts_root':'governance/receipts'})):
            invalid={**realm,field:value}
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.app._validate({'revision':snap['revision'],'files':{**snap['files'],'.ekk/realm.yaml':self.codec.dump_yaml(invalid)}})

    def test_minimal_exact_receipt_is_valid_unverified_nongoverning(self):
        m=self.meta('minimal-decision','decision');self.add(m,'Candidate choice')
        snap=self.store.snapshot();record=self.app._load(snap)[-1]['minimal-decision']
        receipt={'schema':'ekk.receipt/0.1','id':'minimal-receipt','record_id':m['id'],'record_sha256':record['digest'],'record_revision':1,'actor':'owner','adopted_at':'2026-09-07T12:00:00Z','governance_sha256':digest(snap['files']['.ekk/governance.yaml'])}
        self.codec.validate_schema('receipt',receipt)
        self.store.apply({'governance/receipts/minimal.json':json.dumps(receipt).encode()},base=snap['revision'],idempotency_key='import-minimal',principal='owner',policy_digest=digest(snap['files']['.ekk/governance.yaml']))
        report=self.app.doctor();self.assertTrue(report['ok']);self.assertEqual(report['accepted'],[])
        self.assertTrue(any('acceptance unverified' in r['reason'] for r in report['unverified']))
        self.assertFalse(any(r['governs'] for r in self.app.context(['scope'])['records']))

    def test_context_scope_change_needs_accept_on_both_sides(self):
        other=self.meta('other-context','context');other['scope']=['other-context'];self.add(other)
        snap=self.store.snapshot();policy=self.codec.load_yaml(snap['files']['.ekk/governance.yaml']);policy['version']=2
        policy['grants'].extend([{'principal':'partial','actions':['write'],'scopes':['scope','other-context']},{'principal':'partial','actions':['accept'],'scopes':['scope']}])
        self.app.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='partial-context-grant')
        context=self.app._load(self.store.snapshot())[-1]['scope']['metadata'];context['scope']=['other-context'];context['revision']=2
        partial=RealmService(self.store,'partial',codec=self.codec)
        with self.assertRaises(PermissionError):partial.apply(partial.propose({'contexts/scope.md':self.codec.encode(context)}),idempotency_key='shift-context')

    def test_accept_requires_read_of_transitive_pinned_basis(self):
        private=self.meta('private','context');private['scope']=['private'];self.add(private)
        hidden=self.meta('hidden-evidence');hidden['scope']=['private'];self.add(hidden)
        basis=self.meta('visible-basis',relations=[{'rel':'derived_from','target':'hidden-evidence','revision':1}]);self.add(basis)
        choice=self.meta('bounded-choice','decision',relations=[{'rel':'derived_from','target':'visible-basis','revision':1}]);self.add(choice)
        snap=self.store.snapshot();policy=self.codec.load_yaml(snap['files']['.ekk/governance.yaml']);policy['version']=2
        policy['grants'].append({'principal':'partial','actions':['read','write','accept'],'scopes':['scope']})
        self.app.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='partial-accept-grant')
        partial=RealmService(self.store,'partial',codec=self.codec)
        with self.assertRaises(PermissionError):partial.apply(partial.propose({}),idempotency_key='unreadable-accept',accept=['bounded-choice'])
        self.assertEqual(self.app.doctor()['accepted'],[])

    def test_codec_rejects_current_aliases_nonstring_keys_and_oversized_documents(self):
        for raw in (b'first: &x [one]\nsecond: *x\n',b'1: value\n',b'x: '+b'a'*(2*1024*1024)):
            with self.subTest(raw=raw[:30]),self.assertRaises(ValueError):self.codec.load_yaml(raw)
        with self.assertRaises(ValueError):self.codec.decode(b'---\nid: sample\n---\n'+b'a'*(2*1024*1024))
        with self.assertRaises(ValueError):self.codec.load_json(b'{"id":1,"id":2}')
        with self.assertRaises(ValueError):self.codec.load_yaml(b'a: &a [*a]\n',allow_aliases=True)
        bomb=b'a: &a [one, two]\n'+b''.join((chr(98+i)+': &'+chr(98+i)+' ['+', '.join(['*'+chr(97+i)]*10)+']\n').encode() for i in range(8))
        with self.assertRaises(ValueError):self.codec.load_yaml(bomb,allow_aliases=True)

    def test_historical_aliases_are_bounded_diagnosed_and_never_accepted_as_new_yaml(self):
        import yaml
        m=self.meta('historical-alias');shared=['same'];m['first']=shared;m['second']=shared
        raw=b'---\n'+yaml.safe_dump(m).encode()+b'---\noriginal body'
        self.assertIn(b'*id',raw)
        snap=self.store.snapshot();self.store.apply({'records/historical-alias.md':raw},base=snap['revision'],idempotency_key='legacy-alias',principal='owner',policy_digest=digest(snap['files']['.ekk/governance.yaml']))
        historical=self.store.snapshot()
        self.assertFalse(self.app.doctor()['ok'])
        m['revision']=2;fixed=self.codec.encode(m,'original body')
        self.store.apply({'records/historical-alias.md':fixed},base=historical['revision'],idempotency_key='repair-alias',principal='owner',policy_digest=digest(historical['files']['.ekk/governance.yaml']))
        report=self.app.doctor(historical['revision']);self.assertTrue(report['ok'])
        self.assertTrue(any('historical YAML aliases' in r['reason'] for r in report['unverified']))
        self.add(self.meta('after-alias-repair'))
        self.assertEqual(self.store.snapshot(historical['revision'])['files']['records/historical-alias.md'],raw)
        proposed=raw.replace(b'revision: 1',b'revision: 3')
        with self.assertRaises(ValueError):self.app.apply(self.app.propose({'records/historical-alias.md':proposed}),idempotency_key='new-alias')

    def test_migration_evidence_is_owner_scoped_immutable_and_idempotent(self):
        realm=self.app._load(self.store.snapshot())[0]['id']
        rows=[{'realm_id':realm,'origin':{'source_id':'fixture','path':'note.md'},'target_ids':['scope'],'action':'migrate'}]
        result=self.app.retain_migration_evidence(rows,migration_id='fixture-migration',target_realm=realm,idempotency_key='retain-mapping')
        self.assertEqual(result,self.app.retain_migration_evidence(rows,migration_id='fixture-migration',target_realm=realm,idempotency_key='retain-mapping'))
        with self.assertRaises(ValueError):self.app.retain_migration_evidence([{**rows[0],'reason':'different'}],migration_id='fixture-migration',target_realm=realm,idempotency_key='changed-mapping')
        with self.assertRaises(ValueError):self.app.retain_migration_evidence([{**rows[0],'target_ids':['missing']}],migration_id='missing-target',target_realm=realm,idempotency_key='missing-target')
        other=RealmService(self.store,'other',codec=self.codec)
        with self.assertRaises(PermissionError):other.retain_migration_evidence(rows,migration_id='other',target_realm=realm,idempotency_key='other')
        self.assertIn('migrations/fixture-migration/mapping.jsonl',self.store.snapshot()['files'])

    def test_context_budget_rejects_noninteger_and_unbounded_values(self):
        for budget in (float('nan'),float('inf'),True,False,0,-1,1.5,'100',None):
            with self.subTest(budget=budget),self.assertRaises(ValueError):self.app.context(['scope'],budget=budget)

    def test_export_rejects_unverified_grant_selection_and_reports_only_used(self):
        self.add(self.meta('export-item'))
        snap=self.store.snapshot();policy=self.codec.load_yaml(snap['files']['.ekk/governance.yaml']);policy['version']=2
        common={'principal':'owner','destination':'private-target','source_visibility':'private','destination_visibility':'private'}
        policy['export_grants']=[{**common,'id':'used','ids':['export-item']},{**common,'id':'unused','ids':['scope']}]
        self.app.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='export-selection-policy')
        with self.assertRaises(PermissionError):self.app.export(['export-item'],destination='private-target',grants=['used','forged'])
        package=self.app.export(['export-item'],destination='private-target',grants=['used','unused'])
        self.assertEqual(package['grant_ids'],['used'])

    def test_acceptance_pins_entire_consequential_basis_chain(self):
        leaf=self.meta('chain-leaf');self.add(leaf,'original evidence')
        intermediate=self.meta('chain-intermediate',relations=[{'rel':'depends_on','target':'chain-leaf'}]);self.add(intermediate)
        decision=self.meta('chain-decision','decision',relations=[{'rel':'derived_from','target':'chain-intermediate','revision':1}])
        with self.assertRaises(ValueError):self.add(decision,accept=['chain-decision'])
        self.assertEqual(self.app.doctor()['accepted'],[])
        intermediate['revision']=2;intermediate['relations'][0]['revision']=1;self.add(intermediate)
        decision['relations'][0]['revision']=2;self.add(decision,accept=['chain-decision'])
        leaf['revision']=2;self.add(leaf,'new evidence')
        context=self.app.context(['scope'],'uniqueacceptancequery')
        self.assertTrue(any(r['id']=='chain-decision' and r['governs'] for r in context['records']))
        self.assertIn('original evidence',[r['body'] for r in context['records']])
        self.assertNotIn('new evidence',[r['body'] for r in context['records']])

    def test_acceptance_keeps_ordinary_navigation_links_unpinned(self):
        self.add(self.meta('navigation-target'))
        basis=self.meta('navigation-basis',relations=[{'rel':'about','target':'navigation-target'}]);self.add(basis)
        choice=self.meta('navigation-choice','decision',relations=[{'rel':'derived_from','target':'navigation-basis','revision':1}])
        self.add(choice,accept=['navigation-choice'])
        self.assertIn('navigation-choice',self.app.doctor()['accepted'])

    def test_accept_only_actor_can_adopt_but_cannot_submit_record_changes(self):
        self.add(self.meta('adopter-basis'))
        choice=self.meta('adopter-choice','decision',relations=[{'rel':'derived_from','target':'adopter-basis','revision':1}]);self.add(choice)
        snap=self.store.snapshot();policy=self.codec.load_yaml(snap['files']['.ekk/governance.yaml']);policy['version']=2
        policy['grants'].append({'principal':'adopter','actions':['read','accept'],'scopes':['scope']})
        self.app.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='adopter-grant')
        adopter=RealmService(self.store,'adopter',codec=self.codec)
        adopter.apply(adopter.propose({}),idempotency_key='accept-only',accept=['adopter-choice'])
        self.assertIn('adopter-choice',self.app.doctor()['accepted'])
        raw=self.store.snapshot()['files']['records/adopter-choice.md']
        with self.assertRaises(PermissionError):adopter.apply(adopter.propose({'records/adopter-choice.md':raw}),idempotency_key='unchanged-write',accept=['adopter-choice'])

    def test_source_descriptor_deletion_preserves_owned_shared_assets(self):
        original=self.source();asset=original['metadata']['source']['assets'][0]
        with self.assertRaises(ValueError):self.app.apply(self.app.propose({original['path']:None}),idempotency_key='orphan-descriptor')
        second=self.meta('second-source','source',source={'assets':[asset]});self.add(second)
        self.app.apply(self.app.propose({original['path']:None}),idempotency_key='delete-shared-descriptor')
        self.assertIn(asset['path'],self.store.snapshot()['files'])
        self.assertTrue(self.app.doctor()['ok'])
        self.app.apply(self.app.propose({'records/second-source.md':None,asset['path']:None}),idempotency_key='delete-final-source')
        self.assertNotIn(asset['path'],self.store.snapshot()['files'])
        self.assertTrue(self.app.doctor()['ok'])

    def test_proposal_grounds_and_impact_describe_only_submitted_content(self):
        private=self.meta('hidden-context','context');private['scope']=['hidden-context'];self.add(private)
        secret=self.meta('existing-secret');secret['scope']=['hidden-context'];secret['title']='Stored private title';self.add(secret,'Stored private body')
        proposal=self.app.propose({'records/existing-secret.md':None},explanation='Remove a supplied path.')
        self.assertEqual(proposal['grounds'],[]);self.assertEqual(proposal['impact']['scopes'],[])
        self.assertFalse(proposal['impact']['scopes_complete'])
        serialized=json.dumps(proposal)
        for forbidden in ('hidden-context','Stored private title','Stored private body'):self.assertNotIn(forbidden,serialized)
        submitted=self.meta('submitted-note',relations=[{'rel':'derived_from','target':'evidence-identifier','revision':3}])
        proposal=self.app.propose({'records/submitted-note.md':self.codec.encode(submitted)})
        self.assertEqual(proposal['grounds'],[{'id':'evidence-identifier','revision':3}])
        self.assertEqual(proposal['impact'],{'files':['records/submitted-note.md'],'scopes':['scope'],'scopes_complete':True})
        self.assertIn('do not grant permissions',proposal['authority_note'])

    def test_assurance_hidden_basis_is_unknown_and_cannot_be_accepted(self):
        hidden=self.meta('hidden','context');hidden['scope']=['hidden'];self.add(hidden)
        evidence=self.meta('secret-evidence');evidence['scope']=['hidden'];self.add(evidence)
        m=self.decision(assurance={'benefit':{'status':'observed','basis':[{'id':'secret-evidence','revision':1}]}})
        self.add(m)
        snap=self.store.snapshot();policy=self.codec.load_yaml(snap['files']['.ekk/governance.yaml']);policy['version']=2
        policy['grants'].append({'principal':'reader','actions':['read','accept'],'scopes':['scope']})
        self.app.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='restricted-assurance')
        reader=RealmService(self.store,'reader',codec=self.codec)
        report=reader.assurance(['scope'])
        self.assertEqual(report['items'][0]['observed_benefit']['status'],'unknown')
        self.assertNotIn('secret-evidence',json.dumps(report))
        self.assertNotIn('secret-evidence',json.dumps(reader.context(['scope'])))
        with self.assertRaises(PermissionError):reader.apply(reader.propose({}),idempotency_key='hidden-assurance-adopt',accept=['decision'])

    def test_observation_window_future_dates_and_string_trigger(self):
        m=self.decision(review={'triggers':[{'detector':'observation_gap','aspects':['quality'],'max_age_days':2,'starts_at':'2026-09-08T00:00:00Z'}]})
        self.add(m,accept=['decision'])
        self.assertEqual(self.app.review(['scope'])['candidates'],[])
        self.app.clock=lambda:'2026-09-09T00:00:00Z'
        future=self.meta('future-observation','observation',basis=m['basis'],observation={'subject':'decision','observed_at':'2099-01-01T00:00:00Z','aspects':['quality']});self.add(future)
        self.assertIn('unobserved aspects: quality',self.app.review(['scope'])['candidates'][0]['reasons'])
        m['revision']=2;m['review']={'triggers':['observation_gap']};self.add(m,accept=['decision'])
        self.assertEqual(self.app.review(['scope'])['unregistered_conditions'],[{'id':'decision','condition':'observation_gap'}])

    def test_propagation_basis_requires_destination_actor_read_access(self):
        hidden=self.meta('trial-scope','context');hidden['scope']=['trial-scope'];self.add(hidden)
        trial=self.meta('trial');trial['scope']=['trial-scope'];self.add(trial)
        m=self.decision(evolution={'propagation':'explicit','origin_scopes':['trial-scope'],'propagation_basis':[{'id':'trial','revision':1}],'applicability':'target scope only','rollback':'supersede with previous rule'})
        self.add(m)
        snap=self.store.snapshot();policy=self.codec.load_yaml(snap['files']['.ekk/governance.yaml']);policy['version']=2
        policy['grants'].append({'principal':'adopter','actions':['read','accept'],'scopes':['scope']})
        self.app.configure({'.ekk/governance.yaml':self.codec.dump_yaml(policy)},base=snap['revision'],idempotency_key='restricted-trial')
        adopter=RealmService(self.store,'adopter',codec=self.codec)
        with self.assertRaises(PermissionError):adopter.apply(adopter.propose({}),idempotency_key='hidden-trial-adopt',accept=['decision'])

    def test_ungrounded_and_other_scope_observations_do_not_suppress_review(self):
        m=self.decision(review={'triggers':[{'detector':'observation_gap','aspects':['quality'],'max_age_days':2}]})
        self.add(m,accept=['decision'])
        outside=self.meta('outside','context');outside['scope']=['outside'];self.add(outside)
        for key,scope,basis in [('ungrounded','scope',[]),('other-writer','outside',m['basis'])]:
            observation=self.meta(key,'observation',basis=basis,observation={'subject':'decision','observed_at':'2026-09-07T11:00:00Z','aspects':['quality']})
            observation['scope']=[scope];self.add(observation)
        self.assertIn('unobserved aspects: quality',self.app.review(['scope'])['candidates'][0]['reasons'])
        good=self.meta('grounded','observation',basis=m['basis'],observation={'subject':'decision','observed_at':'2026-09-07T11:00:00Z','aspects':['quality']});self.add(good)
        self.assertEqual(self.app.review(['scope'])['candidates'],[])
