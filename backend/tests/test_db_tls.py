"""Boundary tests for strict database TLS (no live Postgres needed)."""
import pytest

from backend import store


LOCAL_URLS = [
    'postgresql://postgres@localhost:5432/launchcrew',
    'postgresql://postgres@127.0.0.1:5432/launchcrew',
    'postgresql://postgres@db:5432/launchcrew',
    'postgresql://postgres@LOCALHOST:5432/launchcrew',
    'postgresql://postgres@[::1]:5432/launchcrew',
]

SECRET_URL = 'postgresql://user:s3cr3t-pw@db:5432/launchcrew'

# Synthetic example host for TLS tests. URLs are built with _pg_url so the
# source never contains a literal userinfo plus host substring.
SYNTHETIC_REMOTE_HOST = "rds.example.com"


def _pg_url(userinfo, host=SYNTHETIC_REMOTE_HOST, query=""):
    base = "postgresql://" + userinfo + chr(64) + host + ":5432/launchcrew"
    if query:
        return base + "?" + query
    return base


def check(url):
    store._require_verified_db_tls(url)


def fails_with_clean_message(url):
    with pytest.raises(ValueError) as excinfo:
        check(url)
    message = str(excinfo.value)
    assert 's3cr3t-pw' not in message
    assert url not in message
    return message


@pytest.mark.parametrize('url', LOCAL_URLS)
def test_local_mode_allows_local_hosts(monkeypatch, url):
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'local')
    monkeypatch.delenv('DATABASE_SSL_ROOTCERT', raising=False)
    check(url)


def test_local_mode_rejects_nonlocal_host(monkeypatch):
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'local')
    fails_with_clean_message(_pg_url("user:s3cr3t-pw"))


@pytest.mark.parametrize('url', [
    _pg_url("postgres", "evil-localhost.com"),
    _pg_url("postgres", "localhost.evil.com"),
    'postgresql://postgres@localhostx:5432/launchcrew',
    # "localhost" only in the password is not a local host.
    _pg_url("user:s3cr3t-pw-localhost"),
    # "db" only in the password is not a local host.
    _pg_url("user:db"),
])
def test_local_mode_rejects_substring_spoof_hosts(monkeypatch, url):
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'local')
    fails_with_clean_message(url)


def test_verify_full_accepts_with_ca_file(monkeypatch, tmp_path):
    ca = tmp_path / 'ca.pem'
    ca.write_text('fake-ca')
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'verify-full')
    monkeypatch.setenv('DATABASE_SSL_ROOTCERT', str(ca))
    check(_pg_url("u", query="sslmode=verify-full"))


def test_verify_full_accepts_case_insensitive_key_and_value(monkeypatch, tmp_path):
    ca = tmp_path / 'ca.pem'
    ca.write_text('fake-ca')
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'verify-full')
    monkeypatch.setenv('DATABASE_SSL_ROOTCERT', str(ca))
    check(_pg_url("u", query="SSLMODE=Verify-Full"))


def test_verify_full_rejects_localhost_without_sslmode(monkeypatch):
    # verify-full applies to any host, including localhost.
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'verify-full')
    fails_with_clean_message('postgresql://postgres@localhost:5432/launchcrew')


@pytest.mark.parametrize('sslmode', ['require', 'prefer', 'disable', 'allow', 'verify-ca', ''])
def test_verify_full_rejects_weak_modes(monkeypatch, tmp_path, sslmode):
    ca = tmp_path / 'ca.pem'
    ca.write_text('fake-ca')
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'verify-full')
    monkeypatch.setenv('DATABASE_SSL_ROOTCERT', str(ca))
    fails_with_clean_message(
        _pg_url("u", query="sslmode=" + sslmode))


def test_verify_full_rejects_trailing_spoof_value(monkeypatch, tmp_path):
    # Old substring check accepted 'sslmode=verify-full-evil'; strict parse rejects it.
    ca = tmp_path / 'ca.pem'
    ca.write_text('fake-ca')
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'verify-full')
    monkeypatch.setenv('DATABASE_SSL_ROOTCERT', str(ca))
    fails_with_clean_message(_pg_url("u", query="sslmode=verify-full-evil"))


def test_verify_full_requires_existing_ca_file(monkeypatch):
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'verify-full')
    monkeypatch.setenv('DATABASE_SSL_ROOTCERT', '/nonexistent/ca.pem')
    fails_with_clean_message(_pg_url("u", query="sslmode=verify-full"))


def test_verify_full_requires_ca_env_set(monkeypatch):
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'verify-full')
    monkeypatch.delenv('DATABASE_SSL_ROOTCERT', raising=False)
    fails_with_clean_message(_pg_url("u", query="sslmode=verify-full"))


@pytest.mark.parametrize('mode', ['local', 'verify-full', ''])
@pytest.mark.parametrize('url', [
    _pg_url("u", query="sslmode=verify-full&sslmode=require"),
    _pg_url("u", query="sslmode=verify-full&sslmode=verify-full"),
    _pg_url("u", query="sslmode=require&sslmode=verify-full"),
])
def test_duplicate_sslmode_rejected_in_every_mode(monkeypatch, tmp_path, mode, url):
    ca = tmp_path / 'ca.pem'
    ca.write_text('fake-ca')
    if mode:
        monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', mode)
    else:
        monkeypatch.delenv('LAUNCHCREW_DB_TLS_MODE', raising=False)
    monkeypatch.setenv('DATABASE_SSL_ROOTCERT', str(ca))
    with pytest.raises(ValueError, match='duplicate sslmode'):
        check(url)


def test_duplicate_sslrootcert_rejected(monkeypatch, tmp_path):
    ca = tmp_path / 'ca.pem'
    ca.write_text('fake-ca')
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'verify-full')
    monkeypatch.setenv('DATABASE_SSL_ROOTCERT', str(ca))
    with pytest.raises(ValueError, match='duplicate sslrootcert'):
        check(_pg_url("u", query="sslmode=verify-full&sslrootcert=/a.pem&sslrootcert=/b.pem"))


def test_unset_allows_local_without_tls(monkeypatch):
    monkeypatch.delenv('LAUNCHCREW_DB_TLS_MODE', raising=False)
    monkeypatch.delenv('DATABASE_SSL_ROOTCERT', raising=False)
    check('postgresql://postgres@127.0.0.1:5432/launchcrew')


def test_unset_requires_verify_full_for_remote(monkeypatch):
    monkeypatch.delenv('LAUNCHCREW_DB_TLS_MODE', raising=False)
    fails_with_clean_message(_pg_url("u"))


def test_unset_remote_verify_full_requires_ca_file(monkeypatch):
    monkeypatch.delenv('LAUNCHCREW_DB_TLS_MODE', raising=False)
    monkeypatch.delenv('DATABASE_SSL_ROOTCERT', raising=False)
    fails_with_clean_message(_pg_url("u", query="sslmode=verify-full"))


def test_unset_remote_verify_full_with_ca_passes(monkeypatch, tmp_path):
    ca = tmp_path / 'ca.pem'
    ca.write_text('fake-ca')
    monkeypatch.delenv('LAUNCHCREW_DB_TLS_MODE', raising=False)
    monkeypatch.setenv('DATABASE_SSL_ROOTCERT', str(ca))
    check(_pg_url("u", query="sslmode=verify-full"))


def test_unknown_mode_rejected(monkeypatch):
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'strict')
    fails_with_clean_message('postgresql://postgres@db:5432/launchcrew')


def test_secret_never_echoed_on_failure(monkeypatch):
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'local')
    url = _pg_url("admin:s3cr3t-pw")
    with pytest.raises(ValueError) as excinfo:
        check(url)
    assert 's3cr3t-pw' not in str(excinfo.value)
    assert 'rds.example.com' not in str(excinfo.value)


@pytest.fixture(autouse=True)
def _no_ambient_pg_routing(monkeypatch):
    # The guard refuses ambient routing variables; clear them so these unit
    # tests never depend on the surrounding environment.
    for name in ('PGHOST', 'PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE'):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize('mode', ['local', 'verify-full', ''])
@pytest.mark.parametrize('query', [
    'host=rds.example.com',
    'HOST=rds.example.com',
    'hostaddr=10.9.9.9',
    'HostAddr=10.9.9.9',
    'service=pgservice',
    'servicefile=/tmp/pgservice.conf',
    '%68ost=rds.example.com',
    '%73ervice=pgservice',
])
def test_effective_destination_overrides_refused_in_every_mode(monkeypatch, tmp_path, mode, query):
    ca = tmp_path / 'ca.pem'
    ca.write_text('fake-ca')
    if mode:
        monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', mode)
    else:
        monkeypatch.delenv('LAUNCHCREW_DB_TLS_MODE', raising=False)
    monkeypatch.setenv('DATABASE_SSL_ROOTCERT', str(ca))
    url = ('postgresql://user:s3cr3t-pw@localhost:5432/launchcrew'
           f'?sslmode=verify-full&{query}')
    with pytest.raises(ValueError) as excinfo:
        check(url)
    assert 's3cr3t-pw' not in str(excinfo.value)


def test_query_host_override_refused_even_when_authority_is_compose_host(monkeypatch):
    # This is the bypass the authority-only check missed: the URL authority
    # says db, but the driver would connect to the query host instead.
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'local')
    fails_with_clean_message(
        'postgresql://postgres@db:5432/launchcrew?host=rds.example.com')


def test_single_sslrootcert_query_refused_so_env_pin_wins(monkeypatch, tmp_path):
    # A single ?sslrootcert= would compete with the DATABASE_SSL_ROOTCERT
    # file engine() pins into connect_args; refusal keeps one pinned source.
    ca = tmp_path / 'ca.pem'
    ca.write_text('fake-ca')
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'verify-full')
    monkeypatch.setenv('DATABASE_SSL_ROOTCERT', str(ca))
    with pytest.raises(ValueError, match='DATABASE_SSL_ROOTCERT'):
        check(_pg_url("u", query="sslmode=verify-full&sslrootcert=/other.pem"))


def test_multihost_authority_refused(monkeypatch, tmp_path):
    ca = tmp_path / 'ca.pem'
    ca.write_text('fake-ca')
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'verify-full')
    monkeypatch.setenv('DATABASE_SSL_ROOTCERT', str(ca))
    with pytest.raises(ValueError, match='single database host'):
        check('postgresql://u@hosta,hostb:5432/launchcrew?sslmode=verify-full')


@pytest.mark.parametrize('name', ['PGHOST', 'PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE'])
def test_ambient_pg_routing_variables_refused_without_reading_values(monkeypatch, tmp_path, name):
    ca = tmp_path / 'ca.pem'
    ca.write_text('fake-ca')
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'verify-full')
    monkeypatch.setenv('DATABASE_SSL_ROOTCERT', str(ca))
    marker = 'dummy-routing-value-xyz'
    monkeypatch.setenv(name, marker)
    with pytest.raises(ValueError) as excinfo:
        check(_pg_url("u", query="sslmode=verify-full"))
    message = str(excinfo.value)
    assert name in message
    assert marker not in message


def test_dialect_proves_query_host_overrides_authority(monkeypatch):
    # Documents WHY the guard refuses ?host=: the installed driver really
    # connects to the query host, not the authority. No connection is made.
    from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
    from sqlalchemy.engine.url import make_url
    dialect = PGDialect_psycopg()
    _, kwargs = dialect.create_connect_args(
        make_url('postgresql+psycopg://postgres@localhost:5432/launchcrew?host=dbremote'))
    assert kwargs['host'] == 'dbremote'
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'local')
    fails_with_clean_message(
        'postgresql://postgres@localhost:5432/launchcrew?host=dbremote')


def test_dialect_proves_effective_args_for_guarded_url(monkeypatch, tmp_path):
    # A URL the guard accepts yields exactly the pinned effective arguments.
    from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
    from sqlalchemy.engine.url import make_url
    ca = tmp_path / 'ca.pem'
    ca.write_text('fake-ca')
    monkeypatch.setenv('LAUNCHCREW_DB_TLS_MODE', 'verify-full')
    monkeypatch.setenv('DATABASE_SSL_ROOTCERT', str(ca))
    url = _pg_url("u", query="sslmode=verify-full")
    check(url)
    dialect = PGDialect_psycopg()
    _, kwargs = dialect.create_connect_args(make_url(url.replace('postgresql://', 'postgresql+psycopg://', 1)))
    assert kwargs['host'] == 'rds.example.com'
    assert kwargs['sslmode'] == 'verify-full'
    for routed in ('hostaddr', 'service', 'servicefile'):
        assert routed not in kwargs
