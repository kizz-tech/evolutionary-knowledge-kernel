"""The disposable parser cache cannot substitute for current source bytes."""
import unittest
from unittest.mock import patch
from ekk.adapters import markdown
from ekk.adapters.markdown import MarkdownCodec


class MarkdownCacheTests(unittest.TestCase):
    def test_repeated_bytes_parse_once_and_return_isolated_graphs(self):
        codec=MarkdownCodec()
        raw=b'---\nid: example\nitems: [{nested: [original]}]\n---\nbody\n'
        with patch.object(codec,'_parse_yaml',wraps=codec._parse_yaml) as parse:
            first=codec.decode(raw)
            first['metadata']['items'][0]['nested'].append('poison')
            second=codec.decode(raw)
            second['metadata']['items'].clear()
            self.assertEqual(codec.decode(raw)['metadata']['items'],[{'nested':['original']}])
            self.assertEqual(parse.call_count,1)

    def test_changed_bytes_and_retained_historical_bytes(self):
        codec=MarkdownCodec()
        old=b'---\nid: item\nrevision: 1\n---\nold\n'
        new=old.replace(b'revision: 1',b'revision: 2').replace(b'old\n',b'new\n')
        self.assertEqual(codec.decode(old)['metadata']['revision'],1)
        self.assertEqual(codec.decode(new)['metadata']['revision'],2)
        self.assertEqual(codec.decode(old),{'metadata':{'id':'item','revision':1},'body':'old\n'})
        self.assertEqual(codec.decode(new.replace(b'new\n',b'other\n'))['body'],'other\n')

    def test_historical_alias_cache_cannot_enable_current_aliases(self):
        codec=MarkdownCodec()
        raw=b'---\na: &a [one]\nb: *a\n---\noriginal\n'
        historic=codec.decode(raw,allow_aliases=True)
        historic['metadata']['a'].append('poison')
        historic['serialization_warnings'].clear()
        with self.assertRaisesRegex(ValueError,'aliases are not supported'):
            codec.decode(raw)
        self.assertEqual(codec.decode(raw,allow_aliases=True)['metadata']['b'],['one'])
        self.assertTrue(codec.decode(raw,allow_aliases=True)['serialization_warnings'])

    def test_invalid_bytes_still_rejected_after_warm_cache(self):
        codec=MarkdownCodec()
        codec.load_yaml(b'id: valid\n')
        for raw in (b'id: first\nid: second\n',b'a: [',b'a: &a [*a]',b'\xff',b'x'*(markdown.MAX_DOCUMENT_BYTES+1)):
            for _ in range(2):
                with self.assertRaises((ValueError,UnicodeError)):
                    codec.load_yaml(raw,allow_aliases=True)
        self.assertEqual(codec.load_yaml(b'id: valid\n'),{'id':'valid'})
        self.assertEqual(len(codec._parse_cache),1)

    def test_digest_collision_never_returns_other_bytes(self):
        codec=MarkdownCodec()
        with patch.object(markdown,'sha256') as digest:
            digest.return_value.digest.return_value=b'collision'
            self.assertEqual(codec.load_yaml(b'id: one')['id'],'one')
            self.assertEqual(codec.load_yaml(b'id: two')['id'],'two')
            self.assertEqual(codec.load_yaml(b'id: one')['id'],'one')

    def test_entry_and_memory_bounds_evict_and_reparse(self):
        codec=MarkdownCodec()
        with patch.object(markdown,'MAX_PARSE_CACHE_ENTRIES',2), patch.object(codec,'_parse_yaml',wraps=codec._parse_yaml) as parse:
            for raw in (b'id: one',b'id: two',b'id: three',b'id: one'):
                codec.load_yaml(raw)
            self.assertEqual(len(codec._parse_cache),2)
            self.assertEqual(parse.call_count,4)
        codec=MarkdownCodec()
        with patch.object(markdown,'MAX_PARSE_CACHE_BYTES',1200):
            for i in range(20):codec.load_yaml(f'id: {i}'.encode())
            self.assertLessEqual(codec._parse_cache_bytes,1200)
            self.assertLess(len(codec._parse_cache),20)
        codec=MarkdownCodec()
        with patch.object(markdown,'MAX_PARSE_CACHE_BYTES',1), patch.object(codec,'_parse_yaml',wraps=codec._parse_yaml) as parse:
            codec.load_yaml(b'id: valid')
            codec.load_yaml(b'id: valid')
            self.assertEqual(parse.call_count,2)
            self.assertEqual(codec._parse_cache_bytes,0)

    def test_schema_validation_is_not_cached_with_parsing(self):
        codec=MarkdownCodec()
        raw=b'id: example'
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'record schema'):
                codec.validate_schema('record',codec.load_yaml(raw))


if __name__=='__main__':unittest.main()
