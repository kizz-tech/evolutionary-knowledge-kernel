from pathlib import Path
import tempfile
import unittest
from ekk.pilot import run

class PilotTests(unittest.TestCase):
    def test_synthetic_closed_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=run(Path(tmp).resolve()/'pilot')
            self.assertTrue(all(result['checks'].values()))
            self.assertFalse(result['scientific_proven'])
            self.assertFalse(result['real_data_used'])
            self.assertEqual([r['passed'] for r in result['capability_outcomes']],[True,False])

if __name__=='__main__':unittest.main()
