"""Build-context photo boundary: fixtures excluded, facts manifest preserved."""
import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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


def test_facts_manifest_preserved_and_no_photo_committed():
    assert (ROOT / 'facts' / 'demo_facts.json').is_file()
    photos = [p for p in (ROOT / 'facts').rglob('*')
              if p.is_file() and p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.heic', '.webp'}]
    assert photos == []
    for name in ('.containerignore', '.dockerignore'):
        assert not _matches(_patterns(name), 'facts/demo_facts.json'), name
