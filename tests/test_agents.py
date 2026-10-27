import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from launchcrew import agents

ROOT = Path(__file__).resolve().parents[1]


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.object(agents, 'AGENTS_DIR', Path(self.temp.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.profile = json.loads((ROOT / 'agents/scout.json').read_text())

    def test_create_load_edit_clone_list(self):
        agents.create_agent(self.profile)
        self.assertEqual(agents.load_agent('Scout'), self.profile)
        self.assertEqual(agents.edit_agent('Scout', {'role': 'Demo Analyst'})['role'], 'Demo Analyst')
        clone = agents.clone_agent('Scout', 'ScoutCopy')
        self.assertEqual(clone['name'], 'ScoutCopy')
        self.assertEqual(len(agents.list_agents()), 2)
        with self.assertRaises(ValueError):
            agents.create_agent(self.profile)

    def test_every_required_field(self):
        for field in agents.REQUIRED_FIELDS:
            profile = copy.deepcopy(self.profile)
            del profile[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                agents.create_agent(profile)

    def test_dry_run_has_no_side_effects(self):
        agents.create_agent(self.profile)
        before = {p.name: p.read_bytes() for p in Path(self.temp.name).iterdir()}
        preview = agents.test_agent('Scout', 'Demo wallet')
        self.assertEqual(preview['profile'], self.profile)
        self.assertTrue(preview['first_action'])
        self.assertFalse(preview['model_called'])
        self.assertFalse(preview['side_effects'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in Path(self.temp.name).iterdir()})

    def test_v1_restrictions(self):
        for updates in ({'tools_allowed': ['send']}, {'spend_limit': 1}, {'name': '../escape'}, {'approval_level': 'automatic'}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                agents.create_agent({**self.profile, **updates})
