"""Build-context photo boundary: fixtures excluded, facts manifest preserved."""
import fnmatch
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PHOTO_SUFFIXES = {'.jpg', '.jpeg', '.png', '.heic', '.webp'}


def _patterns(name):
    return [line.strip() for line in (ROOT / name).read_text().splitlines()
            if line.strip() and not line.strip().startswith('#')]


def _matches(patterns, candidate):
    matched = False
    for pattern in patterns:
        negated = pattern.startswith('!')
        body = pattern[1:] if negated else pattern
        hit = (fnmatch.fnmatch(candidate, body) or fnmatch.fnmatch(candidate, body.rstrip('/'))
               or candidate.startswith(body.rstrip('/**').rstrip('/') + '/')
               or fnmatch.fnmatch('/' + candidate, '/' + body))
        if hit:
            matched = not negated
    return matched


def test_photo_fixtures_excluded_from_build_context():
    for name in ('.containerignore', '.dockerignore'):
        patterns = _patterns(name)
        text = '\n'.join(patterns)
        assert 'demo_photos' in text, name
        for candidate in ('facts/demo_photos/sample-photo.JPG', 'facts/demo_photos/wallet.png',
                          'notes/demo_photos/private.heic', 'tmp/upload.jpeg'):
            assert _matches(patterns, candidate), (name, candidate)


def _tracked_facts_entries():
    # The committed population is the git-tracked set, not the working
    # tree: facts/demo_photos/ is a .gitignore-declared runtime output
    # directory written by backend/sam.py, so ignored files present after
    # a local demo run must not fail this test.
    result = subprocess.run(['git', 'ls-files', '--', 'facts/'],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def test_facts_manifest_preserved_and_no_photo_committed():
    assert (ROOT / 'facts' / 'demo_facts.json').is_file()
    tracked = _tracked_facts_entries()
    assert 'facts/demo_facts.json' in tracked
    photos = [p for p in tracked if Path(p).suffix.lower() in PHOTO_SUFFIXES]
    assert photos == []
    for name in ('.containerignore', '.dockerignore'):
        assert not _matches(_patterns(name), 'facts/demo_facts.json'), name
