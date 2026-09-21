"""Native parsing must preserve EKK's bounded, strict YAML contract."""
import unittest
from unittest.mock import patch
import yaml
from ekk.adapters import markdown


class ParserParityTests(unittest.TestCase):
    def test_native_and_python_preserve_values_and_rejections(self):
        if not hasattr(yaml, 'CSafeLoader'):
            self.skipTest('LibYAML is not installed')
        documents = [
            b'id: test\nrevision: 1\ndate: 2026-09-19\n',
            'id: \u043f\u0440\u0438\u043c\u0435\u0440\ntext: "日本語 😀"\n'.encode(),
            b'values: [yes, no, on, off, null, 01, 0x10, 1.25, .inf]\n',
            b'body: |\n  first\n  second\n',
            b'id: first\nid: second\n', b'1: value\n',
            b'true: value\n', b'null: value\n', b'[a, b]: value\n',
            b'a: &a [one]\nb: *a\n', b'a: &a [*a]\n',
            b'a: &a {name: test}\nb: {<<: *a}\n',
            b'a: !unknown value\n', b'a: !!python/object:os.system {}\n',
            b'a: "\\q"\n', b'a: [', b'a: \x00', b'\xff',
            b'a: 1\n---\nb: 2\n', b'- not\n- mapping\n',
            b'a: "\\uD800"\n',
            b'a: ' + b'[' * 70 + b'0' + b']' * 70,
            b'a: &a [one]\nb: [' + b'*a,' * 129 + b']',
        ]
        for base in (yaml.SafeLoader, yaml.CSafeLoader):
            class StrictLoader(base):
                pass
            StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, markdown._mapping)
            StrictLoader.yaml_implicit_resolvers = markdown._Loader.yaml_implicit_resolvers
            results = []
            with patch.object(markdown, '_Loader', StrictLoader):
                for aliases in (False, True):
                    for raw in documents:
                        try:
                            result = markdown.MarkdownCodec().load_yaml(raw, allow_aliases=aliases)
                            results.append(('ok', result))
                        except (ValueError, UnicodeError, yaml.YAMLError):
                            results.append(('rejected',))
            if base is yaml.SafeLoader:
                expected = results
            else:
                self.assertEqual(expected, results)

    def test_limits_are_checked_before_constructing_values(self):
        with patch.object(markdown, 'MAX_NODES', 4):
            with self.assertRaisesRegex(ValueError, 'node limit'):
                markdown.MarkdownCodec().load_yaml(b'a: [one, two, three]')
        with patch.object(markdown, 'MAX_DEPTH', 2):
            with self.assertRaisesRegex(ValueError, 'nesting'):
                markdown.MarkdownCodec().load_yaml(b'a: [[one]]')


if __name__ == '__main__':
    unittest.main()
