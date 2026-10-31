"""Voice edit measurement: edits per draft with and without a voice profile.

Runs the deterministic keyless pipeline (no model calls, no network, no
database) once per evaluation product in two arms:

- Arm A (without voice): memory claims only.
- Arm B (with voice): the same claims plus one synthetic voice profile
  carrying a single banned term picked from that product's own claims.

Voice samples are style context only and never become facts. The banned
term only adds Checker blocks with concrete reasons, so Arm B v2 drafts
drop the claims containing the term while Arm A keeps them. The report
holds numbers only: per-product counts, character distances between the
two arms' v2 drafts, and summary medians and totals. No claim text, no
draft text, no prose verdicts, and no quality or preference inferences.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from launchcrew import run as pipeline_run  # noqa: E402
from launchcrew.voice_profile import validate_profile  # noqa: E402

SCRIPT_VERSION = "voice-edits/v1"
VOICE_TITLE = "Synthetic evaluation voice"


def load_products(dataset_path):
    """Group dataset cases by product with the union of confirmed facts."""
    raw = Path(dataset_path).read_bytes()
    dataset = json.loads(raw.decode("utf-8"))
    cases = dataset.get("cases", [])
    if not isinstance(cases, list) or not cases:
        raise ValueError("Dataset has no cases list")
    products = {}
    for case in cases:
        product = case.get("product")
        if not isinstance(product, str) or not product.strip():
            raise ValueError("Dataset case is missing a product label")
        facts = case.get("confirmed_facts", [])
        if not isinstance(facts, list):
            raise ValueError("Dataset case has invalid confirmed_facts")
        entry = products.setdefault(product, [])
        for fact in facts:
            if isinstance(fact, str) and fact.strip() and fact not in entry:
                entry.append(fact)
    ordered = sorted(products)
    if not ordered:
        raise ValueError("Dataset has no products")
    return ordered, products, hashlib.sha256(raw).hexdigest()


def word_tokens(text):
    """Lowercase alphanumeric word tokens in order."""
    tokens = []
    current = []
    for ch in text:
        if ch.isalnum() or ch == "_":
            current.append(ch)
        elif current:
            tokens.append("".join(current).casefold())
            current = []
    if current:
        tokens.append("".join(current).casefold())
    return tokens


def pick_banned_term(claims):
    """Pick a whole-word banned term from the product's own claims.

    Prefers the token in the most claims (length 4 or more, not pure
    digits) that still leaves at least one claim unblocked, so the Arm B
    draft stays nonempty. Falls back to the most common token overall.
    """
    if not claims:
        raise ValueError("Product has no claims")
    claim_token_sets = [set(word_tokens(c)) for c in claims]
    counts = {}
    for tokens in claim_token_sets:
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
    total = len(claims)
    eligible = sorted(
        token
        for token, count in counts.items()
        if len(token) >= 4 and not token.isdigit() and count < total
    )
    if eligible:
        best_count = max(counts[token] for token in eligible)
        winners = [token for token in eligible if counts[token] == best_count]
        return sorted(winners)[0]
    fallback = sorted(
        (token for token in counts if len(token) >= 4 and not token.isdigit()),
        key=lambda token: (-counts[token], token),
    )
    if not fallback:
        raise ValueError("Product claims hold no usable banned term")
    return fallback[0]


def split_sentences(text):
    """Split draft text on sentence boundaries, dropping empties."""
    parts = []
    for chunk in str(text).replace("\n", " ").split("."):
        stripped = chunk.strip()
        if stripped:
            parts.append(stripped.casefold())
    return parts


def levenshtein(left, right):
    """Character-level edit distance between two strings."""
    left, right = str(left), str(right)
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_ch in enumerate(left, 1):
        current = [i]
        for j, right_ch in enumerate(right, 1):
            cost = 0 if left_ch == right_ch else 1
            current.append(min(current[j - 1] + 1, previous[j] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


def sentences_changed(before_post, after_post):
    """Count Arm A v2 sentences absent from the Arm B v2 text."""
    after_blob = " ".join(split_sentences(after_post))
    return sum(1 for sentence in split_sentences(before_post) if sentence not in after_blob)


def median(values):
    """Median of a nonempty list of numbers."""
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def voice_block_count(check):
    """Count blocks in a check section carrying a voice reason."""
    total = 0
    for entry in (check or {}).get("blocked_claims", []):
        reason = entry.get("reason", "") if isinstance(entry, dict) else ""
        if isinstance(reason, str) and reason.startswith("Blocked by voice profile"):
            total += 1
    return total


def run_arm(idea, claims, voice_snapshot, voice_ref):
    """Run the deterministic pipeline once and return the receipt."""
    captured = []
    with tempfile.TemporaryDirectory() as directory:
        out = str(Path(directory) / "voice_eval_run.json")
        pipeline_run.run_pipeline(
            idea,
            ROOT / "facts" / "demo_facts.json",
            ROOT / "agents",
            out,
            seed_unverified_claim=False,
            model_enabled=False,
            visual_verifier=None,
            receipt_writer=lambda receipt, path: captured.append(receipt),
            memory_claims=list(claims),
            voice_snapshot=voice_snapshot,
            voice_ref=voice_ref,
        )
    if not captured:
        raise RuntimeError("Pipeline produced no receipt")
    return captured[0]


def measure_product(product, claims, index):
    """Run both arms for one product and return numbers only."""
    idea = "Evaluation draft for %s" % product
    receipt_a = run_arm(idea, claims, None, None)
    term = pick_banned_term(claims)
    snapshot = validate_profile(
        {
            "examples": [
                {
                    "input": "Synthetic draft %d about evaluation layout" % number,
                    "output": "Synthetic revision %d about evaluation layout" % number,
                }
                for number in (1, 2, 3)
            ],
            "banned_terms": [term],
        }
    )
    voice_ref = {"id": "eval_voice_%02d" % index, "title": VOICE_TITLE}
    receipt_b = run_arm(idea, claims, snapshot, voice_ref)

    v1_a = receipt_a.get("checker_v1", {})
    v2_a = receipt_a.get("checker_v2", {})
    v1_b = receipt_b.get("checker_v1", {})
    v2_b = receipt_b.get("checker_v2", {})
    draft_a = receipt_a.get("maker_draft_v2", {})
    draft_b = receipt_b.get("maker_draft_v2", {})
    post_a = draft_a.get("post", "")
    post_b = draft_b.get("post", "")
    email_a = draft_a.get("email", "")
    email_b = draft_b.get("email", "")

    arm_a = {
        "v1_blocked": int(v1_a.get("blocked_count", 0)),
        "v2_blocked": int(v2_a.get("blocked_count", 0)),
        "v2_post_chars": len(post_a),
        "v2_email_chars": len(email_a),
        "v2_claims": len(draft_a.get("claims", [])),
    }
    arm_b = {
        "v1_blocked": int(v1_b.get("blocked_count", 0)),
        "v2_blocked": int(v2_b.get("blocked_count", 0)),
        "v1_voice_blocks": voice_block_count(v1_b),
        "v2_post_chars": len(post_b),
        "v2_email_chars": len(email_b),
        "v2_claims": len(draft_b.get("claims", [])),
    }
    return {
        "product": product,
        "claims_total": len(claims),
        "arm_a": arm_a,
        "arm_b": arm_b,
        "post_distance": levenshtein(post_a, post_b),
        "email_distance": levenshtein(email_a, email_b),
        "sentences_changed": sentences_changed(post_a, post_b),
        "voice_blocked_claims": arm_a["v2_claims"] - arm_b["v2_claims"],
    }


def summarize(rows):
    """Medians and totals across products, numbers only."""
    return {
        "product_count": len(rows),
        "median_post_distance": median([row["post_distance"] for row in rows]),
        "median_email_distance": median([row["email_distance"] for row in rows]),
        "median_sentences_changed": median([row["sentences_changed"] for row in rows]),
        "median_arm_a_v1_blocked": median([row["arm_a"]["v1_blocked"] for row in rows]),
        "median_arm_b_v1_blocked": median([row["arm_b"]["v1_blocked"] for row in rows]),
        "total_arm_a_v1_blocked": sum(row["arm_a"]["v1_blocked"] for row in rows),
        "total_arm_b_v1_blocked": sum(row["arm_b"]["v1_blocked"] for row in rows),
        "total_arm_b_v1_voice_blocks": sum(row["arm_b"]["v1_voice_blocks"] for row in rows),
        "total_voice_blocked_claims": sum(row["voice_blocked_claims"] for row in rows),
        "total_claims": sum(row["claims_total"] for row in rows),
    }


def get_source_sha(explicit=None):
    """Accept an explicit SHA or record git HEAD without fabricating one."""
    if explicit:
        text = str(explicit).strip()
        if text:
            return {"sha": text, "method": "explicit argument"}
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        sha = (proc.stdout or "").strip()
        if proc.returncode == 0 and sha:
            return {"sha": sha, "method": "git rev-parse HEAD"}
    except Exception:
        pass
    return {"sha": "unknown", "method": "unavailable; not fabricated"}


def evaluate(dataset_path, source_sha=None):
    """Run both arms per product and return the numbers-only report."""
    products, claims_by_product, digest = load_products(dataset_path)
    rows = [
        measure_product(product, claims_by_product[product], index)
        for index, product in enumerate(products, 1)
    ]
    return {
        "script": SCRIPT_VERSION,
        "dataset_path": str(dataset_path),
        "dataset_sha256": digest,
        "source_commit": get_source_sha(source_sha),
        "arm_a": "without voice profile",
        "arm_b": "with synthetic voice profile (one banned term)",
        "products": rows,
        "summary": summarize(rows),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Measure per-draft edits with and without a voice profile."
    )
    parser.add_argument("--dataset", default="evaluation/dataset_v1.json")
    parser.add_argument("--out", default="")
    parser.add_argument("--source-sha", default="")
    args = parser.parse_args(argv)
    report = evaluate(args.dataset, source_sha=args.source_sha or None)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
