"""Public source stays English while exact translation provenance remains verifiable."""
import hashlib
import json
from pathlib import Path
import re
import unittest
from ekk.reference_export import FILES

class PublicEnglishTests(unittest.TestCase):
    def test_english_and_translation_integrity(self):
        root=Path(__file__).resolve().parents[1]
        for name in FILES:
            text=(root/name).read_text()
            self.assertIsNone(re.search(r"[\u0400-\u04ff]",text),name)
        manifest=json.loads((root/'translation-manifest.json').read_text())
        for row in manifest['files']:
            self.assertEqual(hashlib.sha256((root/row['path']).read_bytes()).hexdigest(),row['sha256'],row['path'])
