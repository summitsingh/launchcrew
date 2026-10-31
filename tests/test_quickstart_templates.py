"""Slice 5 foundation: quick-start templates stay fictional and unconfirmed.

Offline only. No network, no credentials, no publishing.
"""

import copy
import json
import re
import unittest
from pathlib import Path

from launchcrew import quickstart_templates as qt
from launchcrew.facts import load_facts, parse_product_facts

ROOT = Path(__file__).resolve().parents[1]
WEB_COMPONENT = ROOT / "web" / "src" / "components" / "quickstart-templates.tsx"
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"\+?\d[\d .()-]{7,}\d")


def _raw_text(body):
    return json.dumps(body)


class TemplateFileTests(unittest.TestCase):
    def test_four_templates_listed_with_kinds(self):
        listed = qt.list_quickstart_templates()
        self.assertEqual(
            [t["template_id"] for t in listed],
            ["quickstart_wallet", "quickstart_food", "quickstart_mobile_app", "quickstart_local_service"],
        )
        self.assertEqual(
            [t["kind"] for t in listed], ["wallet", "food", "mobile_app", "local_service"]
        )
        for entry in listed:
            self.assertTrue(entry["fictional"])
            self.assertTrue(entry["confirmation_required"])

    def test_files_label_fictional_and_require_confirmation(self):
        for template_id in qt.TEMPLATE_IDS:
            with self.subTest(template=template_id):
                body = qt.load_quickstart_template(template_id)
                self.assertTrue(body["fictional"])
                self.assertTrue(body["confirmation_required"])
                self.assertIn("Fictional example", body["fictional_note"])
                self.assertIn("unconfirmed", body["fictional_note"].lower())
                self.assertIn("confirm", body["fictional_note"].lower())

    def test_suggested_body_matches_owner_intake_format(self):
        for template_id in qt.TEMPLATE_IDS:
            with self.subTest(template=template_id):
                suggested = qt.quickstart_suggestions(template_id)
                parsed = parse_product_facts(copy.deepcopy(suggested))
                self.assertEqual(parsed["confirmed_claims"], [])
                # Every supplied value is a suggestion, never evidence.
                self.assertGreater(len(parsed["suggested"]), 0)
                values = {s["value"] for s in parsed["suggested"]}
                for name in ("material", "contents", "size", "price"):
                    entry = suggested.get(name)
                    if entry and entry.get("value"):
                        self.assertIn(entry["value"], values)

    def test_selection_never_confirms(self):
        for template_id in qt.TEMPLATE_IDS:
            with self.subTest(template=template_id):
                selected = qt.apply_quickstart_selection(template_id)
                parsed = parse_product_facts(copy.deepcopy(selected))
                self.assertEqual(parsed["confirmed_claims"], [])
                for field in parsed["fields"]:
                    self.assertFalse(field["confirmed"])
                    self.assertIsNone(field["claim"])
                # Mutating the returned copy must not affect the file.
                selected["price"]["value"] = "CHANGED"
                fresh = qt.quickstart_suggestions(template_id)
                self.assertNotEqual(fresh["price"]["value"], "CHANGED")

    def test_unknown_template_rejected(self):
        with self.assertRaises(KeyError):
            qt.load_quickstart_template("quickstart_spaceship")

    def test_existing_format_keys_stay_unapproved(self):
        # Reconciled with the flat facts-file shape (approved_claims /
        # sources keys present) without approving any example claim.
        for template_id in qt.TEMPLATE_IDS:
            with self.subTest(template=template_id):
                body = qt.load_quickstart_template(template_id)
                self.assertEqual(body["approved_claims"], [])
                self.assertIsInstance(body["sources"], list)
                self.assertTrue(body["sources"])
                self.assertIn("unconfirmed", " ".join(body["sources"]).lower())

    def test_legacy_evidence_gate_refuses_template_files(self):
        # Fail closed: no template file may load as approved facts.
        for template_id in qt.TEMPLATE_IDS:
            with self.subTest(template=template_id):
                path = ROOT / qt.TEMPLATE_FILES[template_id]
                with self.assertRaises(ValueError):
                    load_facts(path)

    def test_prefill_envelope_is_unconfirmed_with_provenance(self):
        prefill = qt.build_prefill("quickstart_food")
        self.assertEqual(prefill["template_id"], "quickstart_food")
        parsed = parse_product_facts(copy.deepcopy(prefill["suggested_facts"]))
        self.assertEqual(parsed["confirmed_claims"], [])
        keys = set(prefill["provenance"])
        self.assertIn("price", keys)
        self.assertIn("founder_note", keys)
        self.assertIn("allowed_claims[0]", keys)
        for key, record in prefill["provenance"].items():
            self.assertEqual(record["template_id"], "quickstart_food")
            self.assertTrue(record["example_value"])
            self.assertFalse(record["owner_attested"])

    def test_coincident_real_values_without_template_are_not_blocked(self):
        # An ordinary owner fact that happens to read like an example is
        # legitimate when no template was ever used for that field.
        prefill = qt.build_prefill("quickstart_food")
        example_price = prefill["suggested_facts"]["price"]["value"]
        ordinary = {
            "price": {"value": example_price, "confirmed": True, "source": "owner"},
        }
        parse_product_facts(copy.deepcopy(ordinary))
        self.assertEqual(qt.find_unreviewed_template_fields(ordinary, {}), [])
        qt.assert_template_review_complete(ordinary, {})
        # Provenance for OTHER fields does not taint this one either.
        others = {k: v for k, v in prefill["provenance"].items() if k != "price"}
        self.assertEqual(qt.find_unreviewed_template_fields(ordinary, others), [])

    def test_confirmed_unchanged_template_field_is_rejected(self):
        prefill = qt.build_prefill("quickstart_food")
        probe = copy.deepcopy(prefill["suggested_facts"])
        probe["price"] = {
            "value": prefill["suggested_facts"]["price"]["value"],
            "confirmed": True,
            "source": "owner",
        }
        flags = qt.find_unreviewed_template_fields(probe, prefill["provenance"])
        self.assertEqual([(f["field"], f["reason"]) for f in flags], [("price", "unchanged_example")])
        with self.assertRaisesRegex(ValueError, "review incomplete"):
            qt.assert_template_review_complete(probe, prefill["provenance"])

    def test_confirmed_founder_note_example_is_rejected(self):
        prefill = qt.build_prefill("quickstart_mobile_app")
        probe = copy.deepcopy(prefill["suggested_facts"])
        probe["founder_note"] = {
            "value": prefill["suggested_facts"]["founder_note"]["value"],
            "confirmed": True,
            "source": "owner",
        }
        flags = qt.find_unreviewed_template_fields(probe, prefill["provenance"])
        self.assertEqual(
            [(f["field"], f["reason"]) for f in flags], [("founder_note", "unchanged_example")]
        )
        with self.assertRaisesRegex(ValueError, "review incomplete"):
            qt.assert_template_review_complete(probe, prefill["provenance"])

    def test_trivially_modified_example_is_rejected(self):
        # Punctuation, case, or small-token tweaks are not owner review.
        prefill = qt.build_prefill("quickstart_food")
        example = prefill["suggested_facts"]["allowed_claims"][0]["value"]
        for tweak in (
            example + "!",
            example.lower(),
            "  " + example + "  ",
            example.replace("kitchen", "kitchens"),
        ):
            with self.subTest(tweak=tweak):
                probe = copy.deepcopy(prefill["suggested_facts"])
                probe["allowed_claims"][0] = {
                    "value": tweak,
                    "confirmed": True,
                    "source": "owner",
                }
                flags = qt.find_unreviewed_template_fields(probe, prefill["provenance"])
                self.assertEqual(len(flags), 1)
                self.assertIn(
                    flags[0]["reason"], ("unchanged_example", "trivially_modified")
                )
                with self.assertRaises(ValueError):
                    qt.assert_template_review_complete(probe, prefill["provenance"])

    def test_bypass_attempts_fail_closed(self):
        prefill = qt.build_prefill("quickstart_local_service")
        example_price = prefill["suggested_facts"]["price"]["value"]
        # Flipping the source to owner while keeping the example text and
        # skipping the explicit review action still fails: the value is
        # unchanged and unattested.
        probe = copy.deepcopy(prefill["suggested_facts"])
        probe["price"] = {"value": example_price, "confirmed": True, "source": "owner"}
        with self.assertRaises(ValueError):
            qt.assert_template_review_complete(probe, prefill["provenance"])
        # Confirming while leaving demo_template provenance fails even for
        # fully replaced text: the owner never stated a genuine source.
        probe["price"] = {
            "value": "A completely rewritten owner price fact",
            "confirmed": True,
            "source": "demo_template",
        }
        flags = qt.find_unreviewed_template_fields(probe, prefill["provenance"])
        self.assertEqual([(f["field"], f["reason"]) for f in flags], [("price", "provenance_not_updated")])
        # Attestation of an unknown field is rejected, not silently added.
        with self.assertRaises(KeyError):
            qt.attest_prefill_field(prefill["provenance"], "price_eur")

    def test_replaced_or_attested_values_with_genuine_source_pass(self):
        prefill = qt.build_prefill("quickstart_local_service")
        # Substantively replaced text plus a genuine source is review.
        probe = copy.deepcopy(prefill["suggested_facts"])
        probe["price"] = {
            "value": "Weekend group workshop in the park pavilion",
            "confirmed": True,
            "source": "owner",
        }
        self.assertEqual(qt.find_unreviewed_template_fields(probe, prefill["provenance"]), [])
        qt.assert_template_review_complete(probe, prefill["provenance"])
        # Explicit per-field attestation with a genuine source accepts an
        # unchanged value the owner swears is their own real fact.
        example_price = prefill["suggested_facts"]["price"]["value"]
        probe["price"] = {"value": example_price, "confirmed": True, "source": "owner"}
        provenance = qt.attest_prefill_field(prefill["provenance"], "price")
        self.assertTrue(provenance["price"]["owner_attested"])
        self.assertFalse(prefill["provenance"]["price"]["owner_attested"])
        self.assertEqual(qt.find_unreviewed_template_fields(probe, provenance), [])
        qt.assert_template_review_complete(probe, provenance)
        # Unconfirmed prefill output alone is never a violation.
        fresh = qt.build_prefill("quickstart_food")
        self.assertEqual(
            qt.find_unreviewed_template_fields(fresh["suggested_facts"], fresh["provenance"]), []
        )

    def test_ts_component_stays_in_parity_with_json(self):
        # facts/*.json is authoritative; the TSX duplicates values for
        # offline rendering. Every JSON example value must appear in the
        # component source so drift fails instead of shipping silently.
        source = WEB_COMPONENT.read_text(encoding="utf-8")
        missing = [
            value
            for value in qt.iter_template_values()
            if value not in source
        ]
        self.assertEqual(missing, [])

    def test_no_private_identifiers_or_real_brand_facts(self):
        # Invented names only; no contact details that could read as real.
        for template_id in qt.TEMPLATE_IDS:
            with self.subTest(template=template_id):
                body = qt.load_quickstart_template(template_id)
                text = _raw_text(body)
                self.assertNotRegex(text, EMAIL_RE)
                self.assertNotRegex(text, PHONE_RE)
                lowered = text.lower()
                for brand in ("coca", "pepsi", "nike", "apple inc", "samsung", "mcdonald"):
                    self.assertNotIn(brand, lowered)


if __name__ == "__main__":
    unittest.main()
