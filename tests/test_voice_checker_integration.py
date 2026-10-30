"""Voice, context-claim, and readiness integration in the core pipeline.

Synthetic fixtures only. Voice samples use garden and trail style
references. Context checks use the Summit scope with a test workspace.
No network, no database, no credentials.
"""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launchcrew import context_claims, readiness, run
from launchcrew.facts import load_facts
from launchcrew.receipts import load_receipt
from launchcrew.voice_profile import snapshot_version, validate_profile

ROOT = Path(__file__).resolve().parents[1]
WS = "ws-voice-checker-test"


def summit_scope(workspace=WS):
    return {"profile": "summit", "enabled": True, "workspace_id": workspace}


def summit_policy(extra=None, workspace=WS):
    policy = {"profile": "summit", "enabled": True, "workspace_id": workspace}
    if extra:
        policy.update(extra)
    return policy


def _examples(count=3):
    topics = ("garden layout", "trail map", "recipe card")
    out = []
    for i in range(count):
        topic = topics[i % len(topics)]
        out.append({
            "input": "Synthetic draft %d about %s" % (i + 1, topic),
            "output": "Synthetic revision %d about %s" % (i + 1, topic),
        })
    return out


def _voice_snapshot(banned_terms=None):
    payload = {"examples": _examples(3)}
    if banned_terms is not None:
        payload["banned_terms"] = list(banned_terms)
    return validate_profile(payload)


def _run_pipeline(out_path, approve=False, **kwargs):
    with patch.dict(os.environ, {"META_API_KEY": "", "META_WONDER_MODEL": ""}):
        return run.run_pipeline(
            "Demo wallet", ROOT / "facts/demo_facts.json", ROOT / "agents",
            out_path, approve, False, **kwargs)


class VoiceProvenanceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"META_API_KEY": "", "META_WONDER_MODEL": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_receipt_provenance_preserves_style_without_body_leak(self):
        snap = _voice_snapshot(["harbor"])
        ref = {"id": "mem_garden", "title": "Synthetic garden voice",
               "version": snapshot_version(snap)}
        samples = [{"id": "mem_garden", "title": "Synthetic garden voice",
                    "content": "secret garden body line",
                    "text": "secret trail body line",
                    "examples": [{"input": "x", "output": "y"}]}]
        path = Path(self.temp.name) / "voice_prov.json"
        receipt = _run_pipeline(path, voice_snapshot=snap, voice_ref=ref,
                                voice_samples=samples)
        prov = receipt.get("voice_provenance")
        self.assertIsInstance(prov, dict)
        self.assertEqual(prov["sample_count"], 1)
        self.assertTrue(prov["has_voice"])
        self.assertEqual(prov["samples"],
                         [{"id": "mem_garden", "title": "Synthetic garden voice"}])
        self.assertEqual(prov["snapshot_version"], ref["version"])
        self.assertIn("style context", prov["note"])
        self.assertIn("never fact sources", prov["note"])
        rendered = json.dumps(receipt)
        self.assertNotIn("secret garden body line", rendered)
        self.assertNotIn("secret trail body line", rendered)
        self.assertEqual(receipt, load_receipt(path))
        self.assertEqual(load_receipt(path)["voice_provenance"], prov)

    def test_snapshot_only_derives_provenance_without_example_leak(self):
        snap = _voice_snapshot([])
        ref = {"id": "mem_trail", "title": "Synthetic trail voice",
               "version": snapshot_version(snap)}
        path = Path(self.temp.name) / "voice_snap.json"
        receipt = _run_pipeline(path, voice_snapshot=snap, voice_ref=ref)
        prov = receipt.get("voice_provenance")
        self.assertIsInstance(prov, dict)
        self.assertEqual(prov["sample_count"], 1)
        self.assertTrue(prov["has_voice"])
        self.assertIn("mem_trail", prov["note"])
        self.assertNotIn("Synthetic revision 1", json.dumps(prov))

    def test_no_voice_yields_none_provenance(self):
        path = Path(self.temp.name) / "plain.json"
        receipt = _run_pipeline(path)
        self.assertIsNone(receipt.get("voice_provenance"))
        self.assertIsNone(receipt.get("voice_profile"))


class ReadinessIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"META_API_KEY": "", "META_WONDER_MODEL": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_pipeline_attaches_computed_readiness(self):
        path = Path(self.temp.name) / "ready.json"
        receipt = _run_pipeline(path, approve=True)
        attached = receipt.get("readiness")
        self.assertIsInstance(attached, dict)
        self.assertTrue(attached["ready"])
        self.assertEqual(attached["facts"]["status"], "pass")
        self.assertEqual(attached["checker"]["status"], "pass")
        self.assertEqual(attached["approval"]["status"], "current")
        self.assertEqual(attached["photo"]["status"], "pass")
        self.assertEqual(attached["export"]["status"], "pass")
        self.assertEqual(readiness.readiness_of(receipt), attached)
        self.assertEqual(load_receipt(path)["readiness"], attached)

    def test_pending_pipeline_readiness_is_not_ready(self):
        path = Path(self.temp.name) / "pending.json"
        receipt = _run_pipeline(path, approve=False)
        attached = receipt.get("readiness")
        self.assertIsInstance(attached, dict)
        self.assertFalse(attached["ready"])
        self.assertEqual(attached["approval"]["status"], "stale")
        self.assertEqual(attached["export"]["status"], "blocked")

    def test_readiness_fails_closed_when_gates_missing(self):
        path = Path(self.temp.name) / "base.json"
        receipt = _run_pipeline(path, approve=True)
        missing_facts = copy.deepcopy(receipt)
        del missing_facts["product_facts"]
        failed = readiness.readiness_of(missing_facts)
        self.assertEqual(failed["facts"]["status"], "blocked")
        self.assertFalse(failed["ready"])
        missing_check = copy.deepcopy(receipt)
        del missing_check["checker_v2"]
        failed = readiness.readiness_of(missing_check)
        self.assertEqual(failed["checker"]["status"], "blocked")
        self.assertFalse(failed["ready"])
        tampered = copy.deepcopy(receipt)
        tampered["approval_binding"]["digest"] = "0" * 64
        failed = readiness.readiness_of(tampered)
        self.assertEqual(failed["approval"]["status"], "stale")
        self.assertFalse(failed["ready"])
        for bad in ({}, {"status": "completed"}, None, []):
            failed = readiness.readiness_of(bad)
            self.assertFalse(failed["ready"])
            self.assertEqual(failed["export"]["status"], "blocked")


class ContextClaimPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"META_API_KEY": "", "META_WONDER_MODEL": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.facts, _ = load_facts(ROOT / "facts/demo_facts.json")

    def _facts_with(self, *claims):
        facts = copy.deepcopy(self.facts)
        for claim in claims:
            if claim not in facts["approved_claims"]:
                facts["approved_claims"].append(claim)
        return facts

    def test_conjunction_boundary_blocks_in_check_pack(self):
        text = "Not blue and genuine leather"
        facts = self._facts_with(text)
        draft = {"claims": [text], "post": text + ".", "email": text + "."}
        result = run.check_pack(draft, facts, context_scope=summit_scope())
        self.assertGreaterEqual(result["blocked_count"], 1)
        reasons = [b["reason"] for b in result["blocked_claims"]]
        self.assertTrue(any("context policy" in r and "never allowed" in r
                            for r in reasons))
        clean = run.check_pack(draft, facts)
        self.assertEqual(clean["blocked_count"], 0)

    def test_trailing_negation_reads_as_affirmative(self):
        text = "Genuine leather wallet not"
        facts = self._facts_with(text)
        draft = {"claims": [text], "post": text + ".", "email": text + "."}
        result = run.check_pack(draft, facts, context_scope=summit_scope())
        self.assertGreaterEqual(result["blocked_count"], 1)
        reasons = [b["reason"] for b in result["blocked_claims"]]
        self.assertTrue(any("never allowed" in r for r in reasons))

    def test_ambiguous_exclusive_blocks_even_when_confirmed(self):
        text = "Not only genuine leather wallet"
        facts = self._facts_with(text)
        draft = {"claims": [text], "post": text + ".", "email": text + "."}
        result = run.check_pack(draft, facts, context_scope=summit_scope())
        self.assertGreaterEqual(result["blocked_count"], 1)
        reasons = [b["reason"] for b in result["blocked_claims"]]
        self.assertTrue(any("ambiguous" in r for r in reasons))

    def test_supported_negation_passes_with_confirmation(self):
        text = "Not genuine leather"
        facts = self._facts_with(text)
        draft = {"claims": [text], "post": text + ".", "email": text + "."}
        result = run.check_pack(draft, facts, context_scope=summit_scope())
        self.assertEqual(result["blocked_count"], 0)
        unsupported = run.check_pack(
            {"claims": [], "post": "Not genuine leather.", "email": "For Austin commuters."},
            self.facts, context_scope=summit_scope())
        self.assertGreaterEqual(unsupported["blocked_count"], 1)
        self.assertTrue(any("context policy" in b["reason"]
                            for b in unsupported["blocked_claims"]))

    def test_conditioning_phrase_needs_confirmation(self):
        text = "Apply conditioner monthly"
        blocked = run.check_pack(
            {"claims": [], "post": text + ".", "email": "For Austin commuters."},
            self.facts, context_scope=summit_scope())
        self.assertGreaterEqual(blocked["blocked_count"], 1)
        reasons = [b["reason"] for b in blocked["blocked_claims"]]
        self.assertTrue(any("context policy" in r and "confirmed sentence" in r
                            for r in reasons))
        facts = self._facts_with(text)
        draft = {"claims": [text], "post": text + ".", "email": text + "."}
        passed = run.check_pack(draft, facts, context_scope=summit_scope())
        self.assertEqual(passed["blocked_count"], 0)

    def test_pipeline_threads_context_scope(self):
        path = Path(self.temp.name) / "ctx.json"
        receipt = _run_pipeline(path, memory_claims=["Genuine leather wallet"],
                                context_scope=summit_scope())
        v1_reasons = [b["reason"] for b in receipt["checker_v1"]["blocked_claims"]]
        self.assertTrue(any("context policy" in r for r in v1_reasons))
        self.assertEqual(receipt["checker_v2"]["blocked_count"], 0)
        self.assertNotIn("Genuine leather wallet", receipt["maker_draft_v2"]["post"])
        self.assertNotIn("Genuine leather wallet",
                         receipt["maker_draft_v2"]["claims"])

    def test_pipeline_conjunction_boundary(self):
        path = Path(self.temp.name) / "ctx_conj.json"
        receipt = _run_pipeline(path, memory_claims=["Not blue and genuine leather"],
                                context_scope=summit_scope())
        v1_reasons = [b["reason"] for b in receipt["checker_v1"]["blocked_claims"]]
        self.assertTrue(any("context policy" in r and "never allowed" in r
                            for r in v1_reasons))
        self.assertEqual(receipt["checker_v2"]["blocked_count"], 0)

    def test_invalid_scope_fails_closed(self):
        bad_scope = {"profile": "summit", "enabled": True}
        draft = {"claims": ["$49"], "post": "$49.", "email": "$49."}
        with self.assertRaises(context_claims.ScopeBindingError):
            run.check_pack(draft, self.facts, context_scope=bad_scope)
        path = Path(self.temp.name) / "ctx_bad.json"
        with self.assertRaises(ValueError):
            _run_pipeline(path, memory_claims=["$49"], context_scope=bad_scope)
        failure = load_receipt(path)
        self.assertEqual(failure["status"], "failed")


if __name__ == "__main__":
    unittest.main()
