import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from poc_contracts.validation import validate_project


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary = validate_project(PROJECT_ROOT)

    def test_total_scenarios(self):
        self.assertEqual(self.summary["scenarios"], 24)

    def test_total_query_points(self):
        self.assertEqual(self.summary["query_points"], 60)

    def test_no_contract_errors(self):
        self.assertEqual(self.summary["errors"], [])

    def test_required_baselines(self):
        self.assertEqual(self.summary["required_baselines"], ["B0", "B1", "B3", "B4"])


if __name__ == "__main__":
    unittest.main()
