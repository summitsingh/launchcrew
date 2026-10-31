"""Landing page offer parity sentinel.

Deterministic checker for ad-to-landing-page offer parity. Ad networks
penalize merchants when the price in the ad does not match the price on
the destination landing page, or when the landing page footer lacks
required legal policy links (Privacy Policy, Terms of Service, and
Refund Policy).

Stdlib only, pure functions, no network access. Accepts landing page
HTML or text as an input string.
"""

import re

LANDING_PARITY_VERSION = "landing-parity/v1"

__all__ = [
    "LANDING_PARITY_VERSION",
    "REQUIRED_POLICIES",
    "audit_landing_page_parity",
    "extract_prices",
    "verify_legal_footer",
    "verify_price_parity",
]

# Required legal policies keyed by canonical policy id.
REQUIRED_POLICIES = (
    "privacy_policy",
    "terms_of_service",
    "refund_policy",
)

# Currency amounts like $49, $49.99, $1,299.00, £20, €35.
# Allows optional whitespace between symbol and digits ("$ 49").
_PRICE_RE = re.compile(r"[$\u00a3\u20ac]\s?\d[\d,]*(?:\.\d{1,2})?")

# Anchor tags: tolerant of malformed HTML, never raises.
_ANCHOR_RE = re.compile(
    r"<a\b[^>]*>(.*?)</a\s*>", re.IGNORECASE | re.DOTALL
)
_HREF_RE = re.compile(
    r"""href\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))""",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]*>")


def _normalize_price(raw):
    """Normalize one raw price match to canonical form."""
    text = re.sub(r"\s+", "", raw)
    return text


def extract_prices(text):
    """Extract currency amounts from text or HTML.

    Args:
        text: ad text or landing page HTML/text.

    Returns:
        Sorted unique list of price strings such as "$49",
        "$49.99", "£20", or "€35". Non-string input yields [].
    """
    if not isinstance(text, str) or not text:
        return []
    found = set()
    for match in _PRICE_RE.finditer(text):
        found.add(_normalize_price(match.group()))
    return sorted(found)


def verify_price_parity(ad_text, landing_text_or_html):
    """Check that every price claimed in the ad appears on the page.

    Args:
        ad_text: the ad copy string.
        landing_text_or_html: landing page HTML or text string.

    Returns:
        Dict with parity_passed (bool), ad_prices (list[str]),
        landing_prices (list[str]), and unmatched_ad_prices (list[str]).
        An ad with no prices passes trivially.
    """
    ad_prices = extract_prices(ad_text)
    landing_prices = extract_prices(landing_text_or_html)
    landing_set = set(landing_prices)
    unmatched = [p for p in ad_prices if p not in landing_set]
    return {
        "parity_passed": len(unmatched) == 0,
        "ad_prices": ad_prices,
        "landing_prices": landing_prices,
        "unmatched_ad_prices": unmatched,
    }


def _strip_tags(fragment):
    """Remove nested tags from an anchor body to get anchor text."""
    if not isinstance(fragment, str):
        return ""
    return _TAG_RE.sub("", fragment)


def _policy_present(policy_id, anchors):
    """Return True if any anchor text or href signals the policy."""
    for anchor_text, href in anchors:
        blob = (anchor_text + " " + href).lower()
        if policy_id == "privacy_policy":
            if "privacy" in blob:
                return True
        elif policy_id == "terms_of_service":
            if "terms" in blob or "tos" in blob:
                return True
        elif policy_id == "refund_policy":
            if "refund" in blob or "return" in blob:
                return True
    return False


def verify_legal_footer(html_content):
    """Inspect HTML footer links for required legal policies.

    Checks link anchor text and href attributes case-insensitively.
    Malformed or non-string input is handled gracefully and reports
    every policy as missing rather than raising.

    Args:
        html_content: landing page HTML string.

    Returns:
        Dict with legal_compliance_passed (bool),
        detected_policies (list[str]), and missing_policies (list[str]).
    """
    if not isinstance(html_content, str) or not html_content:
        return {
            "legal_compliance_passed": False,
            "detected_policies": [],
            "missing_policies": list(REQUIRED_POLICIES),
        }
    anchors = []
    try:
        for match in _ANCHOR_RE.finditer(html_content):
            tag_open = html_content[match.start():match.end()]
            href_match = _HREF_RE.search(tag_open)
            href = ""
            if href_match:
                href = (
                    href_match.group(2)
                    or href_match.group(3)
                    or href_match.group(4)
                    or ""
                )
            anchor_text = _strip_tags(match.group(1)).strip()
            anchors.append((anchor_text, href))
    except Exception:
        anchors = []
    detected = [p for p in REQUIRED_POLICIES if _policy_present(p, anchors)]
    missing = [p for p in REQUIRED_POLICIES if p not in detected]
    return {
        "legal_compliance_passed": len(missing) == 0,
        "detected_policies": detected,
        "missing_policies": missing,
    }


def audit_landing_page_parity(ad_text, landing_html):
    """Combine price parity and legal footer checks into one record.

    Args:
        ad_text: the ad copy string.
        landing_html: landing page HTML string.

    Returns:
        Audit dict with version, the full price parity result, the
        full legal footer result, flat copies of their key fields,
        and overall_passed (True only when both checks pass).
    """
    price_check = verify_price_parity(ad_text, landing_html)
    legal_check = verify_legal_footer(landing_html)
    overall = bool(
        price_check["parity_passed"] and legal_check["legal_compliance_passed"]
    )
    return {
        "version": LANDING_PARITY_VERSION,
        "overall_passed": overall,
        "parity_passed": price_check["parity_passed"],
        "legal_compliance_passed": legal_check["legal_compliance_passed"],
        "ad_prices": price_check["ad_prices"],
        "landing_prices": price_check["landing_prices"],
        "unmatched_ad_prices": price_check["unmatched_ad_prices"],
        "detected_policies": legal_check["detected_policies"],
        "missing_policies": legal_check["missing_policies"],
        "price_check": price_check,
        "legal_check": legal_check,
    }
