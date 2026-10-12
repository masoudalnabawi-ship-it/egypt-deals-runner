import unittest
from pathlib import Path


class WorkflowPriceGuardTests(unittest.TestCase):
    def test_evidence_diagnosis_skips_unavailable_price(self):
        workflow = Path(".github/workflows/v15-live-probe.yml").read_text()
        section = workflow.split(
            "- name: Diagnose evidence (non-sensitive summary)", 1
        )[1].split("- name: Prepare validated price observation", 1)[0]

        self.assertIn(
            "steps.probe.outputs.price_unavailable != 'true'",
            section,
        )


if __name__ == "__main__":
    unittest.main()
