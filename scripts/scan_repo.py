"""LaunchCrew public repository pattern scan, using only the standard library.

Counts are matching lines per check. Findings show paths and check types only,
with line numbers for the punctuation and legacy brand checks. No values print.
Patterns are assembled so this source and synthetic tests can scan cleanly.
This is a pattern check, not a general secret or PII detection guarantee.
"""
import argparse
from collections import Counter
import os
from pathlib import Path
import re


# Only this script path is exempt from the personal-name check.
SCRIPT_PATH = Path(__file__).resolve()
EXCLUDED = {'.git', '__pycache__'}
CHECKS = {
    'em_dash': re.compile(chr(0x2014)),
    'legacy_brand': re.compile('Company' + ' OS', re.IGNORECASE),
    'email': re.compile(r'(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+'),
    'phone': re.compile(
        r'(?<!\w)(?:\+?1[ .-]?)?(?:\([2-9]\d{2}\)|[2-9]\d{2})'
        r'[ .-]?[2-9]\d{2}[ .-]?\d{4}(?!\w)'),
    'street_address': re.compile(
        r'\b(?:\d{1,6}\s+(?:(?:[NSEW]|North|South|East|West)\.?\s+)?'
        r'(?:[\w.-]+\s+){1,6}'
        r'(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Court|Ct|'
        r'Boulevard|Blvd|Way|Place|Pl|Parkway|Pkwy|Circle|Cir|Terrace|Ter|'
        r'Trail|Trl|Highway|Hwy)\b|P\.?\s*O\.?\s+Box\s+\d+\b)',
        re.IGNORECASE),
    'secret': re.compile(
        '(?:' + 'AK' + 'IA' + '|' + 'gh' + 'p_' + '|' + 'gh' + 'o_'
        + '|' + 's' + 'k-' + ')'
        + r'|\b[\w]*(?:api[_-]?key)[\w]*[\x22\x27]?\s*[:=]\s*'
        + r'[\x22\x27]?[A-Za-z0-9_./+=-]{20,}', re.IGNORECASE),
    'personal_name': re.compile('Summit' + ' Singh|' + 'summit' + 'singh', re.IGNORECASE),
}


def scan_repo(root):
    """Return (path, check, line) findings; fail closed on unreadable paths."""
    root = Path(root)
    findings = []

    def walk_error(error):
        findings.append((Path(error.filename or root), 'read_error', None))

    if not root.is_dir():
        return [(root, 'read_error', None)]
    for directory, dirs, files in os.walk(root, onerror=walk_error):
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED)
        for name in sorted(files):
            if name in EXCLUDED:
                continue
            path = Path(directory) / name
            try:
                content = path.read_bytes().decode('utf-8', errors='replace')
            except OSError:
                findings.append((path, 'read_error', None))
                continue
            for line_number, line in enumerate(content.splitlines(), 1):
                for check, pattern in CHECKS.items():
                    candidate = line
                    if check == 'personal_name':
                        owner = 'summit' + 'singh'
                        for reference in ('https://github.com/' + owner + '/launchcrew',
                                          'launchcrew.' + owner + '.com'):
                            candidate = candidate.replace(reference, '')
                    if not pattern.search(candidate):
                        continue
                    if (check == 'personal_name' and path.resolve() == SCRIPT_PATH
                            ):
                        continue
                    findings.append((path, check, line_number))
    return findings


def main():
    parser = argparse.ArgumentParser(description='LaunchCrew repository pattern scan')
    parser.add_argument('root', nargs='?', default='.')
    args = parser.parse_args()
    findings = scan_repo(args.root)
    for path, check, line in findings:
        location = str(path)
        if check in {'em_dash', 'legacy_brand'}:
            location += ':' + str(line)
        print(location + ': ' + check)
    counts = Counter(check for _, check, _ in findings)
    print('Scan result: ' + ('fail' if findings else 'pass'))
    for check in (*CHECKS, 'read_error'):
        print(check + ': ' + str(counts[check]))
    return int(bool(findings))


if __name__ == '__main__':
    raise SystemExit(main())
