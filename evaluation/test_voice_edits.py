"""Unit tests for the voice edit measurement script.

Covers the pure metric helpers and the banned-term picker with synthetic
inputs only. No pipeline runs, no database, no network, no model calls.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.voice_edits import (  # noqa: E402
    levenshtein,
    median,
    pick_banned_term,
    sentences_changed,
    split_sentences,
    summarize,
    voice_block_count,
    word_tokens,
)


def test_levenshtein_counts_character_edits():
    assert levenshtein("", "") == 0
    assert levenshtein("abc", "abc") == 0
    assert levenshtein("", "abc") == 3
    assert levenshtein("abc", "") == 3
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("Mug body is glazed stoneware.", "Mug body is stoneware.") == 7


def test_word_tokens_lowercase_and_split():
    assert word_tokens("Mug body is glazed stoneware") == ["mug", "body", "is", "glazed", "stoneware"]
    assert word_tokens("Blue. Moon!") == ["blue", "moon"]


def test_pick_banned_term_prefers_common_but_not_universal():
    claims = [
        "Mug body is glazed stoneware",
        "Mug holds warm drinks well",
        "Mug body shows a blue glaze",
    ]
    assert pick_banned_term(claims) == "body"
    single = ["Only claim about stoneware"]
    assert pick_banned_term(single) == "about"


def test_sentences_changed_counts_absent_arm_a_sentences():
    before = "Mug body is glazed stoneware. Mug holds 350 ml."
    after = "Mug holds 350 ml."
    assert sentences_changed(before, after) == 1
    assert sentences_changed(before, before) == 0
    assert split_sentences("  A.  B.\nC. ") == ["a", "b", "c"]


def test_voice_block_count_only_counts_voice_reasons():
    check = {
        "blocked_claims": [
            {"claim": "x", "reason": "Blocked by voice profile 'V' (voice/v1:abc): banned term 'harbor'"},
            {"claim": "y", "reason": "Blocked by selected memory rule"},
            {"claim": "z", "reason": ""},
        ]
    }
    assert voice_block_count(check) == 1
    assert voice_block_count({}) == 0
    assert voice_block_count(None) == 0


def test_summarize_reports_medians_and_totals():
    rows = [
        {
            "product": "p1",
            "claims_total": 2,
            "arm_a": {"v1_blocked": 0, "v2_blocked": 0, "v2_post_chars": 10, "v2_email_chars": 10, "v2_claims": 2},
            "arm_b": {"v1_blocked": 2, "v2_blocked": 0, "v1_voice_blocks": 2, "v2_post_chars": 5, "v2_email_chars": 5, "v2_claims": 1},
            "post_distance": 5,
            "email_distance": 5,
            "sentences_changed": 1,
            "voice_blocked_claims": 1,
        },
        {
            "product": "p2",
            "claims_total": 4,
            "arm_a": {"v1_blocked": 0, "v2_blocked": 0, "v2_post_chars": 20, "v2_email_chars": 20, "v2_claims": 4},
            "arm_b": {"v1_blocked": 4, "v2_blocked": 0, "v1_voice_blocks": 4, "v2_post_chars": 10, "v2_email_chars": 10, "v2_claims": 2},
            "post_distance": 11,
            "email_distance": 9,
            "sentences_changed": 2,
            "voice_blocked_claims": 2,
        },
    ]
    summary = summarize(rows)
    assert summary["product_count"] == 2
    assert summary["median_post_distance"] == 8.0
    assert summary["median_email_distance"] == 7.0
    assert summary["median_sentences_changed"] == 1.5
    assert summary["total_arm_b_v1_voice_blocks"] == 6
    assert summary["total_voice_blocked_claims"] == 3
    assert summary["total_claims"] == 6
    assert summary["total_arm_a_v1_blocked"] == 0


def test_median_handles_odd_and_even_counts():
    assert median([3]) == 3
    assert median([1, 5]) == 3.0
    assert median([1, 2, 9]) == 2
