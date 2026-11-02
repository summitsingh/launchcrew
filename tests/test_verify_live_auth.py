"""Tests for scripts/verify_live_auth.py refusal paths and provider choice.

Only refusal paths run here: no live verification row is ever written,
no browser session is simulated, and no credential value appears.
"""

import importlib.util
import os
import sys
from pathlib import Path


def load_script():
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location(
        'verify_live_auth', root / 'scripts' / 'verify_live_auth.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_main(monkeypatch, *argv):
    module = load_script()
    monkeypatch.setattr(sys, 'argv', ['verify_live_auth.py', *argv])
    return module.main()


def test_refuses_without_confirmation_flag(monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    assert run_main(monkeypatch, '--provider', 'google') == 2


def test_refuses_when_auth_disabled(monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'false')
    assert run_main(monkeypatch, '--provider', 'google',
                     '--owner-confirmed-live-signin') == 2


def test_accepts_facebook_provider_choice(monkeypatch, capsys):
    # AUTH_ENABLED false refuses after argparse, proving 'facebook'
    # passed the choices gate (an unknown choice exits before this).
    monkeypatch.setenv('AUTH_ENABLED', 'false')
    assert run_main(monkeypatch, '--provider', 'facebook',
                     '--owner-confirmed-live-signin') == 2
    assert 'AUTH_ENABLED' in capsys.readouterr().out


def test_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv('AUTH_ENABLED', 'true')
    try:
        run_main(monkeypatch, '--provider', 'github',
                  '--owner-confirmed-live-signin')
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError('unknown provider must not parse')
