import json
from pathlib import Path
import unittest

from launchcrew import agents

ROOT = Path(__file__).resolve().parents[1]
PRESETS_DIR = ROOT / "agent_presets"
AGENTS_DIR = ROOT / "agents"
PRESET_FILES = ["support.json", "designer.json", "analyst.json", "research.json"]


def load_preset(filename):
    path = PRESETS_DIR / filename
    profile = json.loads(path.read_text(encoding="utf-8"))
    return agents.validate(profile)


def combined_text(profile):
    parts = [
        profile.get("role", ""),
        profile.get("personality", ""),
        profile.get("expertise", ""),
        " ".join(profile.get("decision_rules", [])),
        " ".join(profile.get("veto_scope", [])),
    ]
    return " ".join(parts)


class CrewPresetTests(unittest.TestCase):
    def test_presets_validate_through_existing_schema(self):
        for filename in PRESET_FILES:
            with self.subTest(preset=filename):
                path = PRESETS_DIR / filename
                self.assertTrue(path.is_file(), "missing preset file")
                profile = json.loads(path.read_text(encoding="utf-8"))
                validated = agents.validate(profile)
                self.assertEqual(validated["name"].lower() + ".json", filename)

    def test_inert_placement_outside_agents(self):
        self.assertTrue(PRESETS_DIR.is_dir(), "presets dir missing")
        self.assertNotEqual(PRESETS_DIR.resolve(), AGENTS_DIR.resolve())
        for filename in PRESET_FILES:
            with self.subTest(preset=filename):
                self.assertTrue((PRESETS_DIR / filename).is_file())
                self.assertFalse((AGENTS_DIR / filename).exists())
        active_names = {p["name"].lower() for p in agents.list_agents(directory=AGENTS_DIR)}
        preset_names = {name[:-5] for name in PRESET_FILES}
        self.assertTrue(active_names.isdisjoint(preset_names))
        stored = agents.list_agents(directory=PRESETS_DIR)
        self.assertEqual({p["name"].lower() for p in stored}, preset_names)

    def test_zero_spend_and_approve_each(self):
        for filename in PRESET_FILES:
            with self.subTest(preset=filename):
                profile = load_preset(filename)
                self.assertEqual(profile["spend_limit"], 0)
                self.assertNotIsInstance(profile["spend_limit"], bool)
                self.assertEqual(profile["approval_level"], "approve_each")

    def test_no_unsupported_or_network_tools(self):
        network_tokens = ("network", "http", "api", "web", "photo", "signup", "team", "connector")
        for filename in PRESET_FILES:
            with self.subTest(preset=filename):
                profile = load_preset(filename)
                tools = profile["tools_allowed"]
                self.assertTrue(tools, "tools list must not be empty")
                self.assertTrue(set(tools) <= agents.ALLOWED_TOOLS)
                lowered = [t.lower() for t in tools]
                for token in network_tokens:
                    for tool in lowered:
                        self.assertNotIn(token, tool)

    def test_source_confirmation_and_approval_boundaries(self):
        for filename in PRESET_FILES:
            with self.subTest(preset=filename):
                profile = load_preset(filename)
                text = combined_text(profile).lower()
                self.assertIn("source", text)
                self.assertTrue("confirm" in text or "confirmation" in text)
                self.assertIn("approval", text)
                self.assertIn("checker", text)
                self.assertIn("intended", text)
                self.assertIn("would", text)
                self.assertEqual(profile["veto_scope"], [])

    def test_no_claim_of_auto_approval_or_active_running(self):
        forbidden_claims = (
            "without approval",
            "without review",
            "without confirmation",
            "already runs",
            "currently runs",
            "is active",
            "is running",
        )
        for filename in PRESET_FILES:
            with self.subTest(preset=filename):
                profile = load_preset(filename)
                text = combined_text(profile).lower()
                compact = "".join(ch for ch in text if ch.isalnum())
                self.assertNotIn("autoapprov", compact)
                self.assertNotIn("auto", text)
                for claim in forbidden_claims:
                    self.assertNotIn(claim, text)
                self.assertTrue("would not approve" in text or "do not approve" in text)
                self.assertIn("bypass review", text)

    def test_no_personal_data_fixtures(self):
        forbidden_tokens = ("@", "password", "passwd", "credential", "secret")
        path_tokens = ("/users/", "/home/", "http")
        for filename in PRESET_FILES:
            with self.subTest(preset=filename):
                profile = load_preset(filename)
                raw = json.dumps(profile).lower()
                for token in forbidden_tokens + path_tokens:
                    self.assertNotIn(token, raw)
                self.assertIsInstance(profile["examples"], list)
                for example in profile["examples"]:
                    blob = (example.get("input", "") + " " + example.get("approved_output", "")).lower()
                    self.assertNotIn("@", blob)

    def test_conservative_role_boundaries(self):
        support = combined_text(load_preset("support.json")).lower()
        self.assertIn("faq", support)
        self.assertIn("facts file", support)

        designer = combined_text(load_preset("designer.json")).lower()
        self.assertIn("original", designer)
        self.assertTrue("would not generate" in designer or "do not generate" in designer)
        self.assertIn("no image processing", designer)

        analyst = combined_text(load_preset("analyst.json")).lower()
        self.assertIn("owner entered", analyst)
        self.assertTrue("would not invent" in analyst or "do not invent" in analyst)
        self.assertIn("no invented metrics", analyst)

        research = combined_text(load_preset("research.json")).lower()
        self.assertIn("unverified", research)
        self.assertIn("owner confirmation", research)
        self.assertIn("checker approval", research)


if __name__ == "__main__":
    unittest.main()
