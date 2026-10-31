"""Focused checks for channel presentation candidates.

Hand-built fixtures only. No model calls, no network, no live proof.
"""
import copy
import unittest

from launchcrew.channel_variants import (
    APPROVAL_NOTE,
    BUNDLE_KIND,
    CHANNELS,
    FACEBOOK_MAX_CHARS,
    STATUS_CANDIDATE,
    STATUS_NEEDS_REVISION,
    SOURCE_LABEL,
    VARIANT_KIND,
    X_MAX_CHARS,
    build_channel_variants,
    build_email_variant,
    build_facebook_variant,
    build_instagram_variant,
    build_linkedin_variant,
    build_x_variant,
    split_sentences,
    validate_facebook_variant,
    validate_x_variant,
)

ALL_CHANNELS = ("x", "linkedin", "instagram", "email", "facebook")


def assert_candidate_fields(testcase, variant, expect_valid):
    testcase.assertEqual(variant["variant_kind"], VARIANT_KIND)
    testcase.assertFalse(variant["exportable"])
    testcase.assertFalse(variant["independently_exportable"])
    testcase.assertTrue(variant["requires_checker_binding"])
    testcase.assertIsNone(variant["checker_approval"])
    testcase.assertIsNone(variant["receipt_id"])
    testcase.assertIn("not independently exportable", variant["approval_note"].lower())
    testcase.assertIn("no checker approval", variant["approval_note"].lower())
    testcase.assertIn("receipt binding", variant["approval_note"].lower())
    testcase.assertIn("current approved checker", variant["approval_note"].lower())
    if expect_valid:
        testcase.assertTrue(variant["content_valid"])
        testcase.assertEqual(variant["status"], STATUS_CANDIDATE)
    else:
        testcase.assertFalse(variant["content_valid"])
        testcase.assertEqual(variant["status"], STATUS_NEEDS_REVISION)
    testcase.assertNotEqual(variant["status"], "ready")
    meta = variant["metadata"]
    testcase.assertEqual(meta["variant_kind"], VARIANT_KIND)
    testcase.assertFalse(meta["exportable"])
    testcase.assertFalse(meta["independently_exportable"])
    testcase.assertTrue(meta["requires_checker_binding"])
    testcase.assertIsNone(meta["checker_approval"])
    testcase.assertIsNone(meta["receipt_id"])
    testcase.assertEqual(meta["status"], variant["status"])


class ChannelVariantTests(unittest.TestCase):
    def test_x_limit_is_280(self):
        self.assertEqual(X_MAX_CHARS, 280)

    def test_facebook_bound_is_explicit_and_conservative(self):
        self.assertEqual(FACEBOOK_MAX_CHARS, 2000)
        self.assertGreater(FACEBOOK_MAX_CHARS, X_MAX_CHARS)
        self.assertLess(FACEBOOK_MAX_CHARS, 63206)
        self.assertIn("facebook", CHANNELS)
        self.assertIn("facebook", list(ALL_CHANNELS))

    def test_x_exact_280_boundary_is_content_valid_candidate(self):
        sentence = "A" * 279 + "."
        self.assertEqual(len(sentence), 280)
        variant = build_x_variant(sentence, [])
        self.assertEqual(len(variant["text"]), 280)
        assert_candidate_fields(self, variant, True)
        self.assertIsNone(variant["trim_note"])
        check = validate_x_variant(variant["text"], [], sentence)
        self.assertTrue(check["ok"])
        self.assertTrue(check["content_valid"])
        self.assertFalse(check["exportable"])
        self.assertFalse(check["independently_exportable"])
        self.assertEqual(check["char_count"], 280)

    def test_x_overlong_first_sentence_refuses_without_fragment(self):
        sentence = "B" * 280 + "."
        self.assertEqual(len(sentence), 281)
        variant = build_x_variant(sentence, [])
        assert_candidate_fields(self, variant, False)
        self.assertEqual(variant["text"], "")
        self.assertIn("revision", variant["reason"].lower())
        self.assertIn("280", variant["reason"])
        check = validate_x_variant(sentence, [], sentence)
        self.assertFalse(check["ok"])
        self.assertFalse(check["content_valid"])
        self.assertFalse(check["exportable"])
        self.assertTrue(any("280" in r for r in check["reasons"]))

    def test_decimal_price_does_not_split_sentence(self):
        draft = "Price is $49.99 today. It ships soon."
        parts = split_sentences(draft)
        self.assertEqual(len(parts), 2)
        self.assertIn("$49.99", parts[0])
        self.assertEqual(parts[1], "It ships soon.")
        sized = "Size is 3.5 inches. Good."
        sized_parts = split_sentences(sized)
        self.assertEqual(len(sized_parts), 2)
        self.assertIn("3.5", sized_parts[0])

    def test_price_decimal_exact_match_boundaries(self):
        draft = "Vegan leather wallet at $49.99. Designed in Texas."
        confirmed = ["Vegan leather wallet", "$49.99", "Designed in Texas"]
        variant = build_x_variant(draft, confirmed)
        assert_candidate_fields(self, variant, True)
        self.assertIn("$49.99", variant["text"])
        good = validate_x_variant(variant["text"], confirmed, draft)
        self.assertTrue(good["ok"])
        self.assertTrue(good["content_valid"])
        self.assertFalse(good["exportable"])
        wrong_price = ["Vegan leather wallet", "$49", "Designed in Texas"]
        check = validate_x_variant(variant["text"], wrong_price, draft)
        self.assertFalse(check["ok"])
        self.assertFalse(check["content_valid"])
        self.assertTrue(any("$49.99" in r or "confirmed" in r for r in check["reasons"]))

    def test_x_trim_keeps_whole_sentences_with_receipt_note(self):
        first = "A" * 100 + "."
        second = "B" * 100 + "."
        third = "C" * 100 + "."
        draft = " ".join([first, second, third])
        variant = build_x_variant(draft, [])
        assert_candidate_fields(self, variant, True)
        self.assertEqual(variant["text"], first + " " + second)
        self.assertLessEqual(len(variant["text"]), 280)
        note = variant["trim_note"]
        self.assertIsNotNone(note)
        self.assertIn("2 of 3", note)
        self.assertIn("280", note)
        self.assertIn("omitted", note)
        self.assertIn("no sentence shortened", note.lower())
        for kept in split_sentences(variant["text"]):
            self.assertIn(kept, draft)
        meta = variant["metadata"]
        self.assertEqual((meta["kept_sentences"], meta["total_sentences"]), (2, 3))
        self.assertEqual(meta["omitted_sentences"], 1)

    def test_audience_and_angle_are_never_rendered_as_facts(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        packed = build_channel_variants(
            draft, confirmed, audience="Mars explorers", campaign_angle="Mars launch"
        )
        for key in ALL_CHANNELS:
            self.assertNotIn("Mars", packed[key]["text"])
        self.assertIn("Mars explorers", str(packed["provenance"]["audience_context"]))
        self.assertIn("Mars launch", str(packed["provenance"]["angle_context"]))
        note = packed["provenance"]["note"].lower()
        self.assertIn("suggestion", note)
        self.assertIn("not verified", note)

    def test_channel_formats_are_distinct_but_verbatim(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        packed = build_channel_variants(draft, confirmed)
        texts = [packed[k]["text"] for k in ALL_CHANNELS]
        self.assertEqual(len(set(texts)), 5)
        self.assertEqual(packed["x"]["text"], draft)
        self.assertTrue(packed["linkedin"]["text"].startswith("Update:"))
        self.assertTrue(packed["instagram"]["text"].endswith("More soon."))
        self.assertEqual(packed["email"]["subject"], "Quick update")
        self.assertIn("Hello,", packed["email"]["body"])
        self.assertIn("Thanks,", packed["email"]["body"])
        self.assertIn("\n\n", packed["facebook"]["text"])
        for key in ALL_CHANNELS:
            body = packed[key]["body"] if key == "email" else packed[key]["text"]
            for sentence in split_sentences(body):
                if sentence in ("Update:", "More soon.", "Hello,", "Thanks,"):
                    continue
                self.assertIn(sentence, draft)

    def test_validator_rejects_cut_sentence_and_invented_price(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        cut = validate_x_variant("Vegan leather wall", confirmed, draft)
        self.assertFalse(cut["ok"])
        self.assertFalse(cut["content_valid"])
        self.assertTrue(any("verbatim" in r for r in cut["reasons"]))
        invented = validate_x_variant("Vegan leather wallet at $99.", confirmed, draft)
        self.assertFalse(invented["ok"])
        self.assertFalse(invented["content_valid"])
        self.assertTrue(
            any("$99" in r or "verbatim" in r or "confirmed" in r for r in invented["reasons"])
        )

    def test_validator_requires_complete_source_sentences_in_order(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        exact_cut = validate_x_variant("Vegan leather wall", confirmed, draft)
        self.assertFalse(exact_cut["ok"])
        self.assertFalse(exact_cut["content_valid"])
        self.assertFalse(exact_cut["exportable"])
        self.assertTrue(
            any("verbatim" in r or "complete" in r for r in exact_cut["reasons"])
        )
        for bad in (
            "Vegan leather wallet",
            "Vegan leather wallet. Designed in Texas",
            "Vegan leather wallet. Designed in Texa",
            "Vegan leather wallet. Designed",
        ):
            with self.subTest(candidate=bad):
                check = validate_x_variant(bad, confirmed, draft)
                self.assertFalse(check["ok"])
                self.assertFalse(check["content_valid"])
                self.assertFalse(check["exportable"])
                self.assertTrue(
                    any("verbatim" in r or "complete" in r for r in check["reasons"])
                )
        reordered = validate_x_variant(
            "Designed in Texas. Vegan leather wallet.", confirmed, draft
        )
        self.assertFalse(reordered["ok"])
        self.assertFalse(reordered["content_valid"])
        self.assertFalse(reordered["exportable"])
        prefix = validate_x_variant("Vegan leather wallet.", confirmed, draft)
        self.assertTrue(prefix["ok"])
        self.assertTrue(prefix["content_valid"])
        self.assertFalse(prefix["exportable"])

    def test_validator_rejects_skipped_first_and_middle_sentences(self):
        first = "Alpha launches today."
        second = "Beta ships soon."
        third = "Gamma follows later."
        draft = " ".join([first, second, third])
        confirmed = []
        for skipped in (
            second,
            third,
            second + " " + third,
            first + " " + third,
        ):
            with self.subTest(candidate=skipped):
                check = validate_x_variant(skipped, confirmed, draft)
                self.assertFalse(check["ok"])
                self.assertFalse(check["content_valid"])
                self.assertFalse(check["exportable"])
                self.assertFalse(check["checks"]["verbatim_ok"])
                self.assertTrue(
                    any(
                        "leading prefix" in r or "verbatim" in r
                        for r in check["reasons"]
                    )
                )
        for good in (first, first + " " + second, draft):
            with self.subTest(candidate=good):
                check = validate_x_variant(good, confirmed, draft)
                self.assertTrue(check["ok"])
                self.assertTrue(check["content_valid"])
                self.assertFalse(check["exportable"])
                self.assertTrue(check["checks"]["verbatim_ok"])

    def test_empty_draft_needs_revision(self):
        variant = build_x_variant("   ", [])
        assert_candidate_fields(self, variant, False)
        self.assertEqual(variant["text"], "")
        self.assertIn("revision", variant["reason"].lower())

    def test_repeat_calls_are_deterministic(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        first = build_channel_variants(draft, confirmed, audience="Austin commuters")
        second = build_channel_variants(draft, confirmed, audience="Austin commuters")
        self.assertEqual(first, second)
        check_first = validate_x_variant(first["x"]["text"], confirmed, draft)
        check_second = validate_x_variant(second["x"]["text"], confirmed, draft)
        self.assertEqual(check_first, check_second)

    def test_caller_inputs_are_unchanged(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        audience = {"segment": "Austin commuters"}
        angle = "Origin story"
        draft_copy = copy.deepcopy(draft)
        confirmed_copy = copy.deepcopy(confirmed)
        audience_copy = copy.deepcopy(audience)
        angle_copy = copy.deepcopy(angle)
        packed = build_channel_variants(draft, confirmed, audience, angle)
        validate_x_variant(packed["x"]["text"], confirmed, draft)
        validate_facebook_variant(packed["facebook"]["text"], confirmed, draft)
        self.assertEqual(draft, draft_copy)
        self.assertEqual(confirmed, confirmed_copy)
        self.assertEqual(audience, audience_copy)
        self.assertEqual(angle, angle_copy)

    def test_x_builder_fails_closed_on_wrong_confirmed_price(self):
        draft = "Vegan leather wallet at $49.99. Designed in Texas."
        wrong_price = ["Vegan leather wallet", "$49", "Designed in Texas"]
        variant = build_x_variant(draft, wrong_price)
        assert_candidate_fields(self, variant, False)
        self.assertEqual(variant["text"], "")
        self.assertFalse(variant["metadata"]["exportable"])
        self.assertEqual(variant["metadata"]["status"], "needs_revision")
        self.assertIn("$49.99", variant["metadata"]["unconfirmed_measured_claims"])
        self.assertIn("$49.99", variant["reason"])
        self.assertIn("revision", variant["reason"].lower())

    def test_x_builder_fails_closed_on_unconfirmed_percent_and_size(self):
        draft = "Launch offer saves 20% today. Bottle holds 500 ml."
        confirmed = ["Launch offer", "Bottle"]
        variant = build_x_variant(draft, confirmed)
        assert_candidate_fields(self, variant, False)
        self.assertEqual(variant["text"], "")
        unconfirmed = variant["metadata"]["unconfirmed_measured_claims"]
        self.assertIn("20%", unconfirmed)
        self.assertTrue(any("500" in t and "ml" in t for t in unconfirmed))

    def test_other_channels_fail_closed_on_unconfirmed_claims(self):
        draft = "Vegan leather wallet at $99. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        for builder in (
            build_linkedin_variant,
            build_instagram_variant,
            build_email_variant,
            build_facebook_variant,
        ):
            variant = builder(draft, confirmed)
            assert_candidate_fields(self, variant, False)
            self.assertEqual(variant["text"], "")
            self.assertFalse(variant["metadata"]["exportable"])
            self.assertIn("$99", variant["metadata"]["unconfirmed_measured_claims"])
            if builder is build_email_variant:
                self.assertEqual(variant["body"], "")

    def test_abbreviation_does_not_split_sentence(self):
        draft = "Dr. Lee is here. Second sentence is here."
        parts = split_sentences(draft)
        self.assertEqual(len(parts), 2)
        self.assertNotIn("Dr.", parts)
        self.assertIn("Dr. Lee", parts[0])
        other = split_sentences("Mr. Smith went home. He left.")
        self.assertEqual(len(other), 2)
        self.assertIn("Mr. Smith", other[0])

    def test_x_trim_never_emits_abbreviation_fragment(self):
        draft = "Dr. Lee " + "Y" * 275 + ". Second sentence here."
        parts = split_sentences(draft)
        self.assertNotIn("Dr.", parts)
        self.assertTrue(parts[0].startswith("Dr. Lee"))
        variant = build_x_variant(draft, [])
        self.assertNotEqual(variant["text"], "Dr.")
        self.assertFalse(variant["text"].endswith("Dr."))
        assert_candidate_fields(self, variant, False)
        self.assertEqual(variant["text"], "")

    def test_facebook_keeps_whole_sentences_with_trim_note(self):
        first = "F" * 798 + "."
        second = "G" * 798 + "."
        third = "H" * 798 + "."
        self.assertEqual(len(first), 799)
        draft = "\n\n".join([first, second, third])
        variant = build_facebook_variant(draft, [])
        assert_candidate_fields(self, variant, True)
        self.assertEqual(variant["text"], first + "\n\n" + second)
        self.assertLessEqual(len(variant["text"]), FACEBOOK_MAX_CHARS)
        note = variant["trim_note"]
        self.assertIsNotNone(note)
        self.assertIn("2 of 3", note)
        self.assertIn(str(FACEBOOK_MAX_CHARS), note)
        self.assertIn("omitted", note)
        self.assertIn("no sentence shortened", note.lower())
        for kept in split_sentences(variant["text"]):
            self.assertIn(kept, draft)
        meta = variant["metadata"]
        self.assertEqual((meta["kept_sentences"], meta["total_sentences"]), (2, 3))
        self.assertEqual(meta["omitted_sentences"], 1)
        check = validate_facebook_variant(variant["text"], [], draft)
        self.assertTrue(check["ok"])
        self.assertTrue(check["content_valid"])
        self.assertFalse(check["exportable"])

    def test_facebook_exact_bound_boundary(self):
        sentence = "K" * (FACEBOOK_MAX_CHARS - 1) + "."
        self.assertEqual(len(sentence), FACEBOOK_MAX_CHARS)
        variant = build_facebook_variant(sentence, [])
        assert_candidate_fields(self, variant, True)
        self.assertIsNone(variant["trim_note"])
        too_long = "L" * FACEBOOK_MAX_CHARS + "."
        refused = build_facebook_variant(too_long, [])
        assert_candidate_fields(self, refused, False)
        self.assertEqual(refused["text"], "")
        self.assertIn(str(FACEBOOK_MAX_CHARS), refused["reason"])

    def test_facebook_builder_fails_closed_on_unconfirmed_claims(self):
        draft = "Launch offer saves 20% today. Bottle holds 500 ml."
        confirmed = ["Launch offer", "Bottle"]
        variant = build_facebook_variant(draft, confirmed)
        assert_candidate_fields(self, variant, False)
        self.assertEqual(variant["text"], "")
        unconfirmed = variant["metadata"]["unconfirmed_measured_claims"]
        self.assertIn("20%", unconfirmed)
        self.assertTrue(any("500" in t and "ml" in t for t in unconfirmed))

    def test_facebook_validator_checks_bound_prefix_and_measured(self):
        first = "Alpha launches today."
        second = "Beta ships soon."
        draft = first + " " + second
        prefix = validate_facebook_variant(first, [], draft)
        self.assertTrue(prefix["ok"])
        self.assertTrue(prefix["content_valid"])
        self.assertFalse(prefix["exportable"])
        skipped = validate_facebook_variant(second, [], draft)
        self.assertFalse(skipped["ok"])
        self.assertFalse(skipped["content_valid"])
        self.assertTrue(
            any("leading prefix" in r or "verbatim" in r for r in skipped["reasons"])
        )
        long_text = "M" * FACEBOOK_MAX_CHARS + "."
        over = validate_facebook_variant(long_text, [], long_text + " Extra here.")
        self.assertFalse(over["ok"])
        self.assertTrue(any(str(FACEBOOK_MAX_CHARS) in r for r in over["reasons"]))
        invented = validate_facebook_variant(
            "Wallet at $99.", ["Wallet"], "Wallet at $99."
        )
        self.assertFalse(invented["ok"])
        self.assertTrue(
            any("$99" in r or "confirmed" in r for r in invented["reasons"])
        )

    def test_facebook_text_is_distinct_but_verbatim(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        packed = build_channel_variants(draft, confirmed)
        facebook_text = packed["facebook"]["text"]
        for other in ("x", "linkedin", "instagram", "email"):
            self.assertNotEqual(facebook_text, packed[other]["text"])
        for sentence in split_sentences(facebook_text):
            self.assertIn(sentence, draft)

    def test_no_candidate_is_independently_exportable(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        packed = build_channel_variants(draft, confirmed)
        for key in ALL_CHANNELS:
            with self.subTest(channel=key):
                assert_candidate_fields(self, packed[key], True)
        provenance = packed["provenance"]
        self.assertEqual(provenance["bundle_kind"], BUNDLE_KIND)
        self.assertFalse(provenance["exportable"])
        self.assertFalse(provenance["independently_exportable"])
        self.assertTrue(provenance["requires_checker_binding"])
        self.assertIsNone(provenance["checker_approval"])
        self.assertIsNone(provenance["receipt_id"])
        self.assertIn(APPROVAL_NOTE, provenance["approval_note"])
        self.assertIn("current approved checker", provenance["note"].lower())
        self.assertIn("receipt binding", provenance["note"].lower())
        self.assertEqual(
            provenance["limits"]["facebook_max_chars"], FACEBOOK_MAX_CHARS
        )

    def test_needs_revision_candidates_also_non_exportable_without_receipt(self):
        draft = "Vegan leather wallet at $99. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        packed = build_channel_variants(draft, confirmed)
        for key in ALL_CHANNELS:
            with self.subTest(channel=key):
                variant = packed[key]
                assert_candidate_fields(self, variant, False)
                self.assertEqual(variant["text"], "")
        provenance = packed["provenance"]
        self.assertFalse(provenance["exportable"])
        self.assertFalse(provenance["independently_exportable"])
        self.assertIsNone(provenance["checker_approval"])
        self.assertIsNone(provenance["receipt_id"])

    def test_validators_report_content_validity_not_export_authority(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        for check in (
            validate_x_variant("Vegan leather wallet.", confirmed, draft),
            validate_facebook_variant("Vegan leather wallet.", confirmed, draft),
        ):
            self.assertTrue(check["ok"])
            self.assertTrue(check["content_valid"])
            self.assertFalse(check["exportable"])
            self.assertFalse(check["independently_exportable"])
            self.assertTrue(check["requires_checker_binding"])
            self.assertIsNone(check["checker_approval"])
            self.assertIsNone(check["receipt_id"])
            self.assertIn("current approved checker", check["approval_note"].lower())
        bad = validate_x_variant("Designed in Texas.", confirmed, draft)
        self.assertFalse(bad["ok"])
        self.assertFalse(bad["content_valid"])
        self.assertFalse(bad["exportable"])
        self.assertFalse(bad["independently_exportable"])

    def test_no_approval_id_invented_anywhere(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        packed = build_channel_variants(draft, confirmed)
        self.assertIsNone(packed["provenance"]["checker_approval"])
        self.assertIsNone(packed["provenance"]["receipt_id"])
        for key in ALL_CHANNELS:
            variant = packed[key]
            self.assertIsNone(variant["checker_approval"])
            self.assertIsNone(variant["receipt_id"])
            self.assertIsNone(variant["metadata"]["checker_approval"])
            self.assertIsNone(variant["metadata"]["receipt_id"])
        blob = str(packed)
        self.assertNotIn("CHK-", blob)
        self.assertNotIn("receipt-123", blob)
        self.assertNotIn("approved-receipt", blob.lower())

    def test_source_label_is_caller_supplied_without_checker_claim(self):
        self.assertEqual(SOURCE_LABEL, "caller_supplied_draft")
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        packed = build_channel_variants(draft, confirmed)
        for key in ALL_CHANNELS:
            self.assertEqual(
                packed[key]["metadata"]["source"], "caller_supplied_draft"
            )
        self.assertEqual(packed["provenance"]["source"], "caller_supplied_draft")
        self.assertNotIn("caller_checked_draft", str(packed))


class AdPolicyLintWiringTests(unittest.TestCase):
    def assert_hit_shape(self, hits):
        self.assertIsInstance(hits, list)
        self.assertTrue(hits)
        for hit in hits:
            self.assertIsInstance(hit, dict)
            self.assertIn("category", hit)
            self.assertIn("match", hit)
            self.assertIn("reason", hit)

    def test_clean_variants_pass_policy(self):
        draft = "Vegan leather wallet. Designed in Texas."
        confirmed = ["Vegan leather wallet", "Designed in Texas"]
        packed = build_channel_variants(draft, confirmed)
        for key in ALL_CHANNELS:
            with self.subTest(channel=key):
                variant = packed[key]
                assert_candidate_fields(self, variant, True)
                self.assertTrue(variant["ad_policy_passed"])
                self.assertEqual(variant["ad_policy_hits"], [])
                self.assertTrue(variant["metadata"]["ad_policy_passed"])
                self.assertEqual(variant["metadata"]["ad_policy_hits"], [])

    def test_guaranteed_flags_absolute_claim_but_stays_valid(self):
        draft = "This wallet is guaranteed to last. Designed in Texas."
        confirmed = ["wallet", "Designed in Texas"]
        for builder in (
            build_x_variant,
            build_linkedin_variant,
            build_instagram_variant,
            build_email_variant,
            build_facebook_variant,
        ):
            with self.subTest(builder=builder.__name__):
                variant = builder(draft, confirmed)
                assert_candidate_fields(self, variant, True)
                self.assertFalse(variant["ad_policy_passed"])
                self.assert_hit_shape(variant["ad_policy_hits"])
                self.assertTrue(
                    any(
                        h["category"] == "absolute_claim"
                        and h["match"] == "guaranteed"
                        for h in variant["ad_policy_hits"]
                    )
                )
                self.assertFalse(variant["metadata"]["ad_policy_passed"])
                self.assertEqual(
                    variant["metadata"]["ad_policy_hits"],
                    variant["ad_policy_hits"],
                )

    def test_percent_sign_flags_absolute_claim(self):
        draft = "Save 100% today with this wallet. Designed in Texas."
        confirmed = ["100%", "wallet", "Designed in Texas"]
        variant = build_linkedin_variant(draft, confirmed)
        assert_candidate_fields(self, variant, True)
        self.assertFalse(variant["ad_policy_passed"])
        self.assert_hit_shape(variant["ad_policy_hits"])
        self.assertTrue(
            any(
                h["category"] == "absolute_claim" and h["match"] == "100%"
                for h in variant["ad_policy_hits"]
            )
        )

    def test_are_you_flags_personal_attribute(self):
        draft = "Are you ready for this wallet. Designed in Texas."
        confirmed = ["wallet", "Designed in Texas"]
        variant = build_x_variant(draft, confirmed)
        assert_candidate_fields(self, variant, True)
        self.assertFalse(variant["ad_policy_passed"])
        self.assert_hit_shape(variant["ad_policy_hits"])
        self.assertTrue(
            any(
                h["category"] == "personal_attribute"
                and h["match"] == "are you"
                for h in variant["ad_policy_hits"]
            )
        )

    def test_ugly_flags_shaming_comparison(self):
        draft = "This ugly wallet ships soon. Designed in Texas."
        confirmed = ["wallet", "Designed in Texas"]
        variant = build_instagram_variant(draft, confirmed)
        assert_candidate_fields(self, variant, True)
        self.assertFalse(variant["ad_policy_passed"])
        self.assert_hit_shape(variant["ad_policy_hits"])
        self.assertTrue(
            any(
                h["category"] == "shaming_comparison" and h["match"] == "ugly"
                for h in variant["ad_policy_hits"]
            )
        )

    def test_needs_revision_variants_carry_clean_policy_fields(self):
        variant = build_x_variant("   ", [])
        assert_candidate_fields(self, variant, False)
        self.assertTrue(variant["ad_policy_passed"])
        self.assertEqual(variant["ad_policy_hits"], [])
        self.assertTrue(variant["metadata"]["ad_policy_passed"])
        self.assertEqual(variant["metadata"]["ad_policy_hits"], [])

    def test_policy_hits_are_deterministic(self):
        draft = "This wallet is guaranteed to last. Designed in Texas."
        confirmed = ["wallet", "Designed in Texas"]
        first = build_facebook_variant(draft, confirmed)
        second = build_facebook_variant(draft, confirmed)
        self.assertEqual(
            first["ad_policy_hits"], second["ad_policy_hits"]
        )
        self.assertEqual(
            first["ad_policy_passed"], second["ad_policy_passed"]
        )
        matches = [h["match"] for h in first["ad_policy_hits"]]
        self.assertEqual(matches, sorted(matches))


if __name__ == "__main__":
    unittest.main()
