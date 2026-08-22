"""Router contract: the state table in skills/gsd-path/SKILL.md must route every
v2 phase token in both `active` and `done` status to a contract file that
exists, and the STATE.md template must only use tokens the router knows."""

import re
import unittest
from pathlib import Path

ROUTER_DIR = Path(__file__).resolve().parents[1] / "skills" / "gsd-path"
ROUTER = ROUTER_DIR / "SKILL.md"
STATE_TEMPLATE = ROUTER_DIR / "templates" / "state.md"

ROW = re.compile(r"^\| `([a-z]+)`(.*?)\| (.*?) \|$")
LINK = re.compile(r"\[[^\]]+\]\(([A-Z-]+\.md)\)")


def state_table():
    rows = []
    for line in ROUTER.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match and match.group(1) != "State":
            rows.append((match.group(1), match.group(2).strip(" ,"), match.group(3)))
    return rows


class RouterContractTests(unittest.TestCase):
    def setUp(self):
        self.rows = state_table()
        self.assertGreater(len(self.rows), 10, "state table not found in SKILL.md")

    def test_template_phase_tokens_match_router(self):
        template = STATE_TEMPLATE.read_text(encoding="utf-8")
        tokens = re.search(r"v2 tokens: (.+)", template).group(1)
        phases = [token.strip() for token in tokens.split("|")]
        routed = {phase for phase, _, _ in self.rows}
        self.assertEqual(sorted(routed), sorted(phases))

    def test_every_phase_is_routed_in_progress_and_done(self):
        by_phase = {}
        for phase, condition, _ in self.rows:
            by_phase.setdefault(phase, set()).add(condition)
        for phase, conditions in by_phase.items():
            joined = " ".join(conditions)
            if phase == "shipped":
                continue
            self.assertTrue(
                "not done" in joined or "active" in joined,
                f"{phase}: no in-progress route",
            )
            self.assertTrue(
                "done" in joined.replace("not done", "") or "blocked" in joined or phase == "ship",
                f"{phase}: no completion route",
            )

    def test_every_route_targets_an_existing_contract(self):
        for phase, condition, action in self.rows:
            links = LINK.findall(action)
            if "stop" in action and not links:
                continue
            self.assertTrue(links, f"{phase} ({condition}): route has no contract link")
            for name in links:
                self.assertTrue((ROUTER_DIR / name).is_file(), f"{phase}: missing {name}")

    def test_ship_blocked_routes_to_patch_mode_or_needs_user(self):
        ship_rows = [row for row in self.rows if row[0] == "ship"]
        actions = " ".join(action for _, _, action in ship_rows)
        self.assertIn("patch mode", actions)
        self.assertIn("NEEDS-USER", actions)


if __name__ == "__main__":
    unittest.main()
