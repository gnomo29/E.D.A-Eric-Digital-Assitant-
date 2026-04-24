import unittest

from objective_planner import ObjectivePlanner
from security_levels import SecurityManager


class AdvancedAgentLayersTests(unittest.TestCase):
    def test_objective_planner_builds_steps(self) -> None:
        planner = ObjectivePlanner()
        plan = planner.build_plan("preparar stream en obs")
        self.assertGreaterEqual(len(plan.steps), 3)
        self.assertIn("OBS", plan.steps[0].text)

    def test_security_manager_flags_high_risk(self) -> None:
        manager = SecurityManager()
        decision = manager.assess("borra memoria y apaga el sistema")
        self.assertIn(decision.risk, {"high", "medium", "low"})
        self.assertEqual(decision.risk, "high")


if __name__ == "__main__":
    unittest.main()
