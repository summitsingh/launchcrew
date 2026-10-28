"""Offline populate provisioner tests with adversarial fake SDKs.

No test contacts AWS or the network. Fake STS, Secrets Manager, and ACM
clients record calls and return canned responses shaped like real APIs.
Caller, metadata, and ACM refusals must make zero value calls (zero
GetSecretValue, PutSecretValue, and ExportCertificate). Scoped calls
prove the master secret value is never read. Idempotency, drift refusal,
partial resume, and ambiguous write readback are proven without rotation.
Privacy scans prove passwords, URLs, and key material never reach output.

Most tests are stdlib only and run without deploy dependencies. TLS reuse
and full populate success need the real third party cryptography backend
for actual offline crypto in RAM; those tests skip honestly when the
deploy-only lock is not installed. The host installs
containers/bootstrap-deploy-requirements.lock isolated after the terminal
and reruns. A skip there means missing deploy deps, not a pass.
"""
import base64
import contextlib
import datetime
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "populate_prereqs.py"

ACCOUNT = "111122223333"
REGION = "us-east-1"
SECRET_MASTER = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:launchcrew-master-AbCd01"
SECRET_RUNTIME = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:launchcrew-runtime-EfGh02"
SECRET_MIGRATION = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:launchcrew-migration-IjKl03"
SECRET_TLS = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:launchcrew-tls-MnOp04"
CERT_ARN = f"arn:aws:acm:{REGION}:{ACCOUNT}:certificate/12345678-90ab-cdef-1234-567890abcde1"
DOMAIN = "launchcrew.summitsingh.com"
DB_HOST = "mydb.abc123.us-east-1.rds.amazonaws.com"
RT_USER = "launchcrew_runtime"
MG_USER = "launchcrew_migration"
RT_PW = "s3ntinel-runtime-pw-9x:A?b#c%d"
MG_PW = "s3ntinel-migration-pw-9x:X!y(z)w"

try:
    import cryptography  # noqa: F401
    HAS_CRYPTO = True
except Exception:
    HAS_CRYPTO = False

try:
    import botocore.config  # noqa: F401
    HAS_BOTOCORE = True
except Exception:
    HAS_BOTOCORE = False


def load_script():
    spec = importlib.util.spec_from_file_location("populate_prereqs",
                                                  SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PP = load_script()


class FakeClientError(Exception):
    def __init__(self, code, message="fake error"):
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


class FakeSTS:
    def __init__(self, account=ACCOUNT, role="InitTaskRole",
                 session="session123", arn_override=None):
        self.calls = []
        self.account = account
        self.role = role
        self.session = session
        self.arn_override = arn_override
        self.fail = False

    def get_caller_identity(self):
        self.calls.append(("get_caller_identity", {}))
        if self.fail:
            raise FakeClientError("AccessDenied", "not authorized")
        if self.arn_override is not None:
            arn = self.arn_override
        else:
            arn = ("arn:aws:sts::%s:assumed-role/%s/%s"
                   % (self.account, self.role, self.session))
        return {"Account": self.account, "Arn": arn,
                "UserId": "ARO123:%s" % self.session}


class FakeSM:
    def __init__(self):
        self.calls = []
        self.store = {}
        self.put_fail_mode = None
        self.put_fail_count = 0
        self.get_fail_next = False

    def seed(self, arn, name, tags=None, secret_string=None,
             version=None):
        if tags is None:
            tags = [{"Key": "Project", "Value": "LaunchCrew"},
                    {"Key": "Environment", "Value": "demo"}]
        self.store[arn] = {"ARN": arn, "Name": name, "Tags": tags,
                           "SecretString": secret_string,
                           "VersionId": version}

    def describe_secret(self, SecretId=""):
        self.calls.append(("describe_secret", {"SecretId": SecretId}))
        entry = self.store.get(SecretId)
        if entry is None:
            raise FakeClientError("ResourceNotFoundException",
                                  "secret not found")
        return {"ARN": entry["ARN"], "Name": entry["Name"],
                "Tags": entry["Tags"]}

    def get_secret_value(self, SecretId=""):
        self.calls.append(("get_secret_value", {"SecretId": SecretId}))
        if self.get_fail_next:
            self.get_fail_next = False
            raise FakeClientError("InternalError", "transient")
        entry = self.store.get(SecretId)
        if entry is None or not entry.get("SecretString"):
            raise FakeClientError("ResourceNotFoundException",
                                  "no version")
        return {"ARN": entry["ARN"], "Name": entry["Name"],
                "VersionId": entry.get("VersionId") or "v1",
                "SecretString": entry["SecretString"]}

    def put_secret_value(self, SecretId="", SecretString="",
                         ClientRequestToken=""):
        self.calls.append(("put_secret_value",
                           {"SecretId": SecretId,
                            "Token": ClientRequestToken}))
        entry = self.store.get(SecretId)
        if entry is None:
            raise FakeClientError("ResourceNotFoundException",
                                  "secret not found")
        if self.put_fail_mode == "raise_after_store":
            entry["SecretString"] = SecretString
            entry["VersionId"] = ClientRequestToken
            self.put_fail_count += 1
            raise FakeClientError("InternalError", "accepted lost")
        if self.put_fail_mode == "raise_no_store":
            self.put_fail_count += 1
            raise FakeClientError("InternalError", "put failed")
        existing_token = entry.get("VersionId") or ""
        existing_value = entry.get("SecretString") or ""
        if existing_token == ClientRequestToken and existing_value:
            if existing_value != SecretString:
                raise FakeClientError("InvalidRequestException",
                                      "same token different content")
            return {"ARN": SecretId, "VersionId": existing_token}
        entry["SecretString"] = SecretString
        entry["VersionId"] = ClientRequestToken
        return {"ARN": SecretId, "VersionId": ClientRequestToken}

    def count(self, op):
        return sum(1 for name, _kw in self.calls if name == op)

    def count_for(self, op, arn):
        total = 0
        for name, kw in self.calls:
            if name == op and kw.get("SecretId") == arn:
                total += 1
        return total

    def put_tokens(self):
        return [kw["Token"] for name, kw in self.calls
                if name == "put_secret_value"]


class FakeACM:
    def __init__(self, domain=DOMAIN, status="ISSUED",
                 export="ENABLED", cert_type="AMAZON_ISSUED",
                 sans=None, tags_ok=True, serial="12AB34CD",
                 now=None):
        self.calls = []
        self.domain = domain
        self.status = status
        self.export = export
        self.cert_type = cert_type
        self.sans = sans if sans is not None else [domain]
        self.tags_ok = tags_ok
        self.serial = serial
        self.now = now
        self.leaf_pem = ""
        self.chain_pem = ""
        self.encrypted_key_pem = ""
        self.export_fail = False
        self.get_fail = False
        self.describe_fail = False

    def _bounds(self):
        current = self.now
        if current is None:
            current = datetime.datetime.now(datetime.timezone.utc)
        before = current - datetime.timedelta(days=30)
        after = current + datetime.timedelta(days=335)
        return before, after

    def describe_certificate(self, CertificateArn=""):
        self.calls.append(("describe_certificate",
                           {"CertificateArn": CertificateArn}))
        if self.describe_fail:
            raise FakeClientError("AccessDenied", "not authorized")
        before, after = self._bounds()
        return {"Certificate": {
            "CertificateArn": CERT_ARN,
            "DomainName": self.domain,
            "SubjectAlternativeNames": list(self.sans),
            "Type": self.cert_type,
            "Status": self.status,
            "Options": {"Export": self.export,
                        "CertificateTransparencyLoggingPreference":
                            "ENABLED"},
            "NotBefore": before,
            "NotAfter": after,
            "Serial": self.serial,
        }}

    def list_tags_for_certificate(self, CertificateArn=""):
        self.calls.append(("list_tags_for_certificate",
                           {"CertificateArn": CertificateArn}))
        if self.tags_ok:
            tags = [{"Key": "Project", "Value": "LaunchCrew"},
                    {"Key": "Environment", "Value": "demo"}]
        else:
            tags = [{"Key": "Project", "Value": "Other"}]
        return {"Tags": tags}

    def get_certificate(self, CertificateArn=""):
        self.calls.append(("get_certificate",
                           {"CertificateArn": CertificateArn}))
        if self.get_fail:
            raise FakeClientError("AccessDenied", "not authorized")
        return {"Certificate": self.leaf_pem,
                "CertificateChain": self.chain_pem}

    def export_certificate(self, CertificateArn="", Passphrase=b""):
        self.calls.append(("export_certificate",
                           {"CertificateArn": CertificateArn}))
        if self.export_fail:
            raise FakeClientError("AccessDenied", "not authorized")
        phrase = bytes(Passphrase or b"")
        if len(phrase) < 4 or len(phrase) > 128:
            raise FakeClientError("InvalidRequestException",
                                  "bad passphrase length")
        for byte in phrase:
            if byte < 32 or byte > 126:
                raise FakeClientError("InvalidRequestException",
                                      "bad passphrase charset")
            if chr(byte) in ("#", "$", "%"):
                raise FakeClientError("InvalidRequestException",
                                      "bad passphrase charset")
        return {"Certificate": self.leaf_pem,
                "CertificateChain": self.chain_pem,
                "PrivateKey": self.encrypted_key_pem}

    def count(self, op):
        return sum(1 for name, _kw in self.calls if name == op)


class EnvHarness(unittest.TestCase):
    def setUp(self):
        PP._known_secrets.clear()
        self.saved = dict(os.environ)
        self.ca_file = tempfile.NamedTemporaryFile(delete=False)
        self.ca_file.write(b"fake-ca-bundle")
        self.ca_file.close()
        os.environ["LAUNCHCREW_EXPECTED_ACCOUNT"] = ACCOUNT
        os.environ["LAUNCHCREW_EXPECTED_REGION"] = REGION
        os.environ["LAUNCHCREW_EXPECTED_ROLE"] = "InitTaskRole"
        os.environ["LAUNCHCREW_MASTER_SECRET_ARN"] = SECRET_MASTER
        os.environ["LAUNCHCREW_RUNTIME_SECRET_ARN"] = SECRET_RUNTIME
        os.environ["LAUNCHCREW_MIGRATION_SECRET_ARN"] = SECRET_MIGRATION
        os.environ["LAUNCHCREW_TLS_SECRET_ARN"] = SECRET_TLS
        os.environ["LAUNCHCREW_CERT_ARN"] = CERT_ARN
        os.environ["LAUNCHCREW_DB_HOST"] = DB_HOST
        os.environ["DATABASE_SSL_ROOTCERT"] = self.ca_file.name
        os.environ["LAUNCHCREW_DB_TLS_MODE"] = "verify-full"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)
        try:
            os.unlink(self.ca_file.name)
        except Exception:
            pass
        PP._known_secrets.clear()

    def make_clients(self, sts=None, sm=None, acm=None):
        return {"sts": sts or FakeSTS(),
                "sm": sm or FakeSM(),
                "acm": acm or FakeACM()}

    def seed_all(self, sm, runtime_value=None, migration_value=None,
                 tls_value=None, tls_version=None,
                 runtime_version="v-runtime-1",
                 migration_version="v-migration-1"):
        sm.seed(SECRET_MASTER, "launchcrew-master")
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string=runtime_value, version=runtime_version)
        sm.seed(SECRET_MIGRATION, "launchcrew-migration",
                secret_string=migration_value,
                version=migration_version)
        sm.seed(SECRET_TLS, "launchcrew-tls",
                secret_string=tls_value, version=tls_version)

    def value_calls(self, sm, acm):
        return (sm.count("get_secret_value") +
                sm.count("put_secret_value") +
                acm.count("export_certificate"))

    def capture(self, func, *args, **kwargs):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            try:
                code = func(*args, **kwargs)
                return code, out.getvalue() + err.getvalue(), None
            except Exception as exc:
                return None, out.getvalue() + err.getvalue(), exc


class ConfigValidationTests(EnvHarness):
    def test_missing_account_refuses_with_zero_calls(self):
        del os.environ["LAUNCHCREW_EXPECTED_ACCOUNT"]
        sm, acm = FakeSM(), FakeACM()
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(sm.calls, [])
        self.assertEqual(acm.calls, [])

    def test_bad_account_shape_refuses(self):
        os.environ["LAUNCHCREW_EXPECTED_ACCOUNT"] = "123"
        sm, acm = FakeSM(), FakeACM()
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_duplicate_arns_refuse_before_any_call(self):
        os.environ["LAUNCHCREW_MIGRATION_SECRET_ARN"] = SECRET_RUNTIME
        sm, acm = FakeSM(), FakeACM()
        clients = self.make_clients(sm=sm, acm=acm)
        _code, _text, exc = self.capture(PP.do_populate, clients)
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(clients["sts"].calls, [])
        self.assertEqual(sm.calls, [])
        self.assertEqual(acm.calls, [])

    def test_localhost_db_refuses(self):
        os.environ["LAUNCHCREW_DB_HOST"] = "localhost"
        sm, acm = FakeSM(), FakeACM()
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_loopback_db_refuses(self):
        os.environ["LAUNCHCREW_DB_HOST"] = "127.0.0.1"
        sm, acm = FakeSM(), FakeACM()
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_missing_ca_refuses(self):
        os.environ["DATABASE_SSL_ROOTCERT"] = "/nonexistent-ca.pem"
        sm, acm = FakeSM(), FakeACM()
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_wrong_tls_mode_refuses(self):
        os.environ["LAUNCHCREW_DB_TLS_MODE"] = "require"
        sm, acm = FakeSM(), FakeACM()
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_wrong_region_in_arn_refuses(self):
        bad = SECRET_RUNTIME.replace(REGION, "us-west-2")
        os.environ["LAUNCHCREW_RUNTIME_SECRET_ARN"] = bad
        sm, acm = FakeSM(), FakeACM()
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)


class CallerTests(EnvHarness):
    def test_wrong_account_makes_zero_value_calls(self):
        sm, acm = FakeSM(), FakeACM()
        self.seed_all(sm, runtime_value="x", migration_value="y")
        sts = FakeSTS(account="999988887777")
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sts=sts, sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(sm.calls, [])
        self.assertEqual(acm.calls, [])
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_wrong_role_makes_zero_value_calls(self):
        sm, acm = FakeSM(), FakeACM()
        self.seed_all(sm, runtime_value="x", migration_value="y")
        sts = FakeSTS(role="OtherRole")
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sts=sts, sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(sm.calls, [])
        self.assertEqual(acm.calls, [])

    def test_sts_failure_makes_zero_value_calls(self):
        sm, acm = FakeSM(), FakeACM()
        sts = FakeSTS()
        sts.fail = True
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sts=sts, sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_session_containing_expected_role_is_refused(self):
        sm, acm = FakeSM(), FakeACM()
        self.seed_all(sm, runtime_value="x", migration_value="y")
        sts = FakeSTS(role="OtherRole", session="InitTaskRole")
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sts=sts, sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(sm.calls, [])
        self.assertEqual(acm.calls, [])
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_role_prefix_and_suffix_impostors_are_refused(self):
        for impostor in ("EvilInitTaskRole", "InitTaskRoleEvil",
                         "InitTaskRole/Admin"):
            sm, acm = FakeSM(), FakeACM()
            self.seed_all(sm, runtime_value="x", migration_value="y")
            sts = FakeSTS(role=impostor)
            _code, _text, exc = self.capture(
                PP.do_populate, self.make_clients(sts=sts, sm=sm, acm=acm))
            self.assertIsInstance(exc, ValueError)
            self.assertEqual(sm.calls, [])
            self.assertEqual(acm.calls, [])
            self.assertEqual(self.value_calls(sm, acm), 0)

    def test_root_federated_and_shape_impostors_are_refused(self):
        bad_arns = [
            "arn:aws:iam::%s:root" % ACCOUNT,
            "arn:aws:sts::%s:federated-user/Bob" % ACCOUNT,
            "arn:aws:sts::%s:assumed-role/InitTaskRole/" % ACCOUNT,
            "arn:aws:sts::%s:assumed-role/InitTaskRole/s1/extra" % ACCOUNT,
            "arn:aws-cn:sts::%s:assumed-role/InitTaskRole/s1" % ACCOUNT,
            "arn:aws:sts:us-east-1:%s:assumed-role/InitTaskRole/s1" % ACCOUNT,
            "arn:aws:iam::%s:assumed-role/InitTaskRole/s1" % ACCOUNT,
            "not-an-arn",
        ]
        for bad in bad_arns:
            sm, acm = FakeSM(), FakeACM()
            self.seed_all(sm, runtime_value="x", migration_value="y")
            sts = FakeSTS(arn_override=bad)
            _code, _text, exc = self.capture(
                PP.do_populate, self.make_clients(sts=sts, sm=sm, acm=acm))
            self.assertIsInstance(exc, ValueError)
            self.assertEqual(sm.calls, [])
            self.assertEqual(acm.calls, [])
            self.assertEqual(self.value_calls(sm, acm), 0)

    def test_arn_account_mismatch_is_refused(self):
        sm, acm = FakeSM(), FakeACM()
        self.seed_all(sm, runtime_value="x", migration_value="y")
        bad = ("arn:aws:sts::999988887777:assumed-role/"
               "InitTaskRole/session123")
        sts = FakeSTS(arn_override=bad)
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sts=sts, sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(sm.calls, [])
        self.assertEqual(acm.calls, [])
        self.assertEqual(self.value_calls(sm, acm), 0)


@unittest.skipUnless(HAS_BOTOCORE, "requires deploy-only botocore, "
                     "host installs isolated lock after terminal")
class MakeClientsTests(unittest.TestCase):
    def test_effective_config_is_total_one_attempt(self):
        from botocore.config import Config as RealConfig
        captured = {}

        def fake_client(service, region_name=None, config=None):
            captured[service] = config
            return ("fake-%s" % service, region_name)

        clients = PP._make_clients(
            REGION, _client_factory=fake_client,
            _config_cls=RealConfig)
        self.assertEqual(set(clients.keys()), {"sts", "sm", "acm"})
        self.assertEqual(set(captured.keys()), {"sts", "sm", "acm"})
        for service, cfg in captured.items():
            self.assertIsInstance(cfg, RealConfig)
            retries = cfg.retries
            self.assertEqual(retries.get("total_max_attempts"), 1)
            self.assertEqual(retries.get("mode"), "standard")
            self.assertNotIn("max_attempts", retries)
            self.assertEqual(cfg.connect_timeout, 5)
            self.assertEqual(cfg.read_timeout, 10)


class SecretMetadataTests(EnvHarness):
    def test_arn_mismatch_makes_zero_value_calls(self):
        sm, acm = FakeSM(), FakeACM()
        self.seed_all(sm, runtime_value="x", migration_value="y")
        sm.store[SECRET_RUNTIME]["ARN"] = SECRET_RUNTIME + "-other"
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_wrong_project_tag_makes_zero_value_calls(self):
        sm, acm = FakeSM(), FakeACM()
        self.seed_all(sm, runtime_value="x", migration_value="y")
        sm.store[SECRET_MIGRATION]["Tags"] = [
            {"Key": "Project", "Value": "Other"},
            {"Key": "Environment", "Value": "demo"}]
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_missing_secret_makes_zero_value_calls(self):
        sm, acm = FakeSM(), FakeACM()
        sm.seed(SECRET_MASTER, "launchcrew-master")
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string="x")
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_master_describe_failure_makes_zero_value_calls(self):
        sm, acm = FakeSM(), FakeACM()
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string="x")
        sm.seed(SECRET_MIGRATION, "launchcrew-migration",
                secret_string="y")
        sm.seed(SECRET_TLS, "launchcrew-tls")
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)


class AcmMetadataTests(EnvHarness):
    def _seed_db(self, sm):
        runtime = json.dumps({"username": RT_USER, "password": RT_PW},
                             sort_keys=True, separators=(',', ':'))
        migration = json.dumps({"username": MG_USER,
                                "password": MG_PW},
                               sort_keys=True, separators=(',', ':'))
        self.seed_all(sm, runtime_value=runtime,
                      migration_value=migration, tls_value=None)

    def test_wrong_domain_makes_zero_value_calls(self):
        sm, acm = FakeSM(), FakeACM(domain="other.example.test",
                                    sans=["other.example.test"])
        self._seed_db(sm)
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_extra_san_makes_zero_value_calls(self):
        sm, acm = FakeSM(), FakeACM(sans=[DOMAIN, "other.example.test"])
        self._seed_db(sm)
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_wrong_type_makes_zero_value_calls(self):
        sm, acm = FakeSM(), FakeACM(cert_type="IMPORTED")
        self._seed_db(sm)
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_pending_status_makes_zero_value_calls(self):
        sm, acm = FakeSM(), FakeACM(status="PENDING_VALIDATION")
        self._seed_db(sm)
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_export_disabled_makes_zero_value_calls(self):
        sm, acm = FakeSM(), FakeACM(export="DISABLED")
        self._seed_db(sm)
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_wrong_acm_tags_make_zero_value_calls(self):
        sm, acm = FakeSM(), FakeACM(tags_ok=False)
        self._seed_db(sm)
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)

    def test_expired_cert_makes_zero_value_calls(self):
        past = (datetime.datetime.now(datetime.timezone.utc) -
                datetime.timedelta(days=400))
        sm = FakeSM()
        acm = FakeACM(now=past + datetime.timedelta(days=800))
        acm._bounds = lambda: (past, past + datetime.timedelta(days=30))
        self._seed_db(sm)
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(self.value_calls(sm, acm), 0)


class TokenAndUrlTests(EnvHarness):
    def test_token_is_deterministic_64_hex(self):
        first = PP._deterministic_token("runtime-db-url-v1",
                                        SECRET_RUNTIME, '{"a":1}')
        second = PP._deterministic_token("runtime-db-url-v1",
                                         SECRET_RUNTIME, '{"a":1}')
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertRegex(first, r"^[0-9a-f]{64}$")

    def test_token_differs_by_purpose_arn_payload(self):
        base = PP._deterministic_token("runtime-db-url-v1",
                                       SECRET_RUNTIME, '{"a":1}')
        other_purpose = PP._deterministic_token("migration-db-url-v1",
                                                SECRET_RUNTIME,
                                                '{"a":1}')
        other_arn = PP._deterministic_token("runtime-db-url-v1",
                                            SECRET_MIGRATION, '{"a":1}')
        other_payload = PP._deterministic_token("runtime-db-url-v1",
                                                SECRET_RUNTIME,
                                                '{"a":2}')
        self.assertNotEqual(base, other_purpose)
        self.assertNotEqual(base, other_arn)
        self.assertNotEqual(base, other_payload)

    def test_canonical_json_is_stable(self):
        payload = {"username": RT_USER, "password": RT_PW,
                   "database-url": "postgresql://x"}
        first = PP._canonical_secret_string(payload)
        second = PP._canonical_secret_string(dict(payload))
        self.assertEqual(first, second)
        self.assertNotIn(" ", first)
        self.assertTrue(first.index("database-url") <
                        first.index("password") <
                        first.index("username"))

    def test_password_percent_encoding_roundtrips(self):
        tricky = "p@ss:w?o#r%d/a b\\q\"z"
        url = PP._build_canonical_db_url(RT_USER, tricky, DB_HOST,
                                         5432, "launchcrew")
        parsed = PP._parse_db_url_strict("check", url, RT_USER,
                                         DB_HOST, "launchcrew")
        self.assertEqual(parsed["password"], tricky)
        self.assertIn("sslmode=verify-full", url)

    def test_generated_password_chars_encode_without_change(self):
        url = PP._build_canonical_db_url(RT_USER, RT_PW, DB_HOST,
                                         5432, "launchcrew")
        parsed = PP._parse_db_url_strict("check", url, RT_USER,
                                         DB_HOST, "launchcrew")
        self.assertEqual(parsed["password"], RT_PW)

    def test_strict_parse_refuses_rerouting_keys(self):
        url = ("postgresql://%s:%s@%s:5432/launchcrew"
               "?sslmode=verify-full&host=other.example.test"
               % (RT_USER, RT_PW, DB_HOST))
        with self.assertRaises(ValueError):
            PP._parse_db_url_strict("check", url, RT_USER, DB_HOST,
                                    "launchcrew")

    def test_strict_parse_refuses_wrong_host(self):
        url = PP._build_canonical_db_url(RT_USER, RT_PW, DB_HOST,
                                         5432, "launchcrew")
        swapped = url.replace(DB_HOST, "other.example.test")
        with self.assertRaises(ValueError):
            PP._parse_db_url_strict("check", swapped, RT_USER,
                                    DB_HOST, "launchcrew")

    def test_strict_parse_requires_verify_full(self):
        url = ("postgresql://%s:%s@%s:5432/launchcrew?sslmode=require"
               % (RT_USER, RT_PW, DB_HOST))
        with self.assertRaises(ValueError):
            PP._parse_db_url_strict("check", url, RT_USER, DB_HOST,
                                    "launchcrew")

    def test_passphrase_alphabet_and_length(self):
        for _ in range(25):
            phrase = PP._generate_passphrase(32)
            self.assertEqual(len(phrase), 32)
            for char in phrase:
                code = ord(char)
                self.assertGreaterEqual(code, 33)
                self.assertLessEqual(code, 126)
                self.assertNotIn(char, ("#", "$", "%"))


class DbPopulateTests(EnvHarness):
    def config(self):
        return PP._load_config()

    def test_missing_url_populates_with_deterministic_token(self):
        sm = FakeSM()
        current = json.dumps({"username": RT_USER, "password": RT_PW},
                             sort_keys=True, separators=(',', ':'))
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string=current, version="v-old")
        result = PP._populate_db_secret(sm, SECRET_RUNTIME, "runtime",
                                        RT_USER, self.config())
        self.assertEqual(result, "populated")
        self.assertEqual(sm.count("put_secret_value"), 1)
        stored = json.loads(sm.store[SECRET_RUNTIME]["SecretString"])
        self.assertEqual(stored["username"], RT_USER)
        self.assertEqual(stored["password"], RT_PW)
        self.assertIn(DB_HOST, stored["database-url"])
        token = sm.put_tokens()[0]
        expected = PP._deterministic_token(
            "runtime-db-url-v1", SECRET_RUNTIME,
            sm.store[SECRET_RUNTIME]["SecretString"])
        self.assertEqual(token, expected)

    def test_same_payload_is_noop_with_zero_put(self):
        sm = FakeSM()
        config = self.config()
        url = PP._build_canonical_db_url(RT_USER, RT_PW,
                                         config["host"],
                                         config["port"],
                                         config["dbname"])
        canonical = PP._canonical_secret_string(
            {"database-url": url, "password": RT_PW,
             "username": RT_USER})
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string=canonical, version="v-current")
        result = PP._populate_db_secret(sm, SECRET_RUNTIME, "runtime",
                                        RT_USER, config)
        self.assertEqual(result, "reused")
        self.assertEqual(sm.count("put_secret_value"), 0)

    def test_endpoint_drift_refuses_with_zero_put(self):
        sm = FakeSM()
        config = self.config()
        other_url = PP._build_canonical_db_url(
            RT_USER, RT_PW, "other.abc123.us-east-1.rds.amazonaws.com",
            5432, "launchcrew")
        drifted = PP._canonical_secret_string(
            {"database-url": other_url, "password": RT_PW,
             "username": RT_USER})
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string=drifted, version="v-current")
        with self.assertRaisesRegex(ValueError, "rotation required"):
            PP._populate_db_secret(sm, SECRET_RUNTIME, "runtime",
                                   RT_USER, config)
        self.assertEqual(sm.count("put_secret_value"), 0)

    def test_malformed_url_refuses_without_rotation(self):
        config = self.config()
        bad_urls = [
            "postgresql://%s:%s@%s:5432/launchcrew"
            "?sslmode=verify-full&host=evil.example.test"
            % (RT_USER, RT_PW, config["host"]),
            "http://%s:%s@%s:5432/launchcrew?sslmode=verify-full"
            % (RT_USER, RT_PW, config["host"]),
            "postgresql://%s:%s@localhost:5432/launchcrew"
            "?sslmode=verify-full" % (RT_USER, RT_PW),
        ]
        for bad_url in bad_urls:
            fresh = FakeSM()
            drifted = PP._canonical_secret_string(
                {"database-url": bad_url, "password": RT_PW,
                 "username": RT_USER})
            fresh.seed(SECRET_RUNTIME, "launchcrew-runtime",
                       secret_string=drifted, version="v-current")
            with self.assertRaisesRegex(ValueError, "malformed"):
                PP._populate_db_secret(fresh, SECRET_RUNTIME, "runtime",
                                       RT_USER, config)
            self.assertEqual(fresh.count("put_secret_value"), 0)

    def test_password_drift_refuses_with_zero_put(self):
        sm = FakeSM()
        config = self.config()
        url = PP._build_canonical_db_url(RT_USER, RT_PW,
                                         config["host"],
                                         config["port"],
                                         config["dbname"])
        drifted = PP._canonical_secret_string(
            {"database-url": url, "password": "different-pw-1",
             "username": RT_USER})
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string=drifted, version="v-current")
        with self.assertRaisesRegex(ValueError, "rotation required"):
            PP._populate_db_secret(sm, SECRET_RUNTIME, "runtime",
                                   RT_USER, config)
        self.assertEqual(sm.count("put_secret_value"), 0)

    def test_username_drift_refuses_with_zero_put(self):
        sm = FakeSM()
        current = json.dumps({"username": "someone_else",
                              "password": RT_PW},
                             sort_keys=True, separators=(',', ':'))
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string=current, version="v-old")
        with self.assertRaisesRegex(ValueError, "rotation required"):
            PP._populate_db_secret(sm, SECRET_RUNTIME, "runtime",
                                   RT_USER, self.config())
        self.assertEqual(sm.count("put_secret_value"), 0)

    def test_malformed_json_never_overwrites(self):
        sm = FakeSM()
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string="not-json{{{", version="v-old")
        with self.assertRaisesRegex(ValueError, "refusing overwrite"):
            PP._populate_db_secret(sm, SECRET_RUNTIME, "runtime",
                                   RT_USER, self.config())
        self.assertEqual(sm.count("put_secret_value"), 0)

    def test_same_token_different_content_fails_closed(self):
        sm = FakeSM()
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string='{"a":1}', version="tok123")
        with self.assertRaises(FakeClientError):
            sm.put_secret_value(SecretId=SECRET_RUNTIME,
                                SecretString='{"a":2}',
                                ClientRequestToken="tok123")

    def test_parallel_identical_puts_share_one_version(self):
        sm = FakeSM()
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string=None, version=None)
        first = sm.put_secret_value(SecretId=SECRET_RUNTIME,
                                    SecretString='{"a":1}',
                                    ClientRequestToken="tok-parallel-1")
        second = sm.put_secret_value(SecretId=SECRET_RUNTIME,
                                     SecretString='{"a":1}',
                                     ClientRequestToken="tok-parallel-1")
        self.assertEqual(first["VersionId"], second["VersionId"])

    def test_accepted_but_unconfirmed_readback_equal_succeeds(self):
        sm = FakeSM()
        current = json.dumps({"username": RT_USER, "password": RT_PW},
                             sort_keys=True, separators=(',', ':'))
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string=current, version="v-old")
        sm.put_fail_mode = "raise_after_store"
        result = PP._populate_db_secret(sm, SECRET_RUNTIME, "runtime",
                                        RT_USER, self.config())
        self.assertEqual(result, "populated")
        self.assertEqual(sm.count("put_secret_value"), 1)
        self.assertEqual(sm.count("get_secret_value"), 2)

    def test_ambiguous_write_with_different_readback_stops(self):
        sm = FakeSM()
        current = json.dumps({"username": RT_USER, "password": RT_PW},
                             sort_keys=True, separators=(',', ':'))
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string=current, version="v-old")
        sm.put_fail_mode = "raise_no_store"
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            PP._populate_db_secret(sm, SECRET_RUNTIME, "runtime",
                                   RT_USER, self.config())
        self.assertEqual(sm.count("put_secret_value"), 1)

    def test_ambiguous_write_with_failed_readback_stops(self):
        sm = FakeSM()
        current = json.dumps({"username": RT_USER, "password": RT_PW},
                             sort_keys=True, separators=(',', ':'))
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string=current, version="v-old")

        original_get = sm.get_secret_value
        calls = {"count": 0}

        def flaky_get(SecretId=""):
            calls["count"] += 1
            if calls["count"] == 1:
                return original_get(SecretId=SecretId)
            raise FakeClientError("InternalError", "readback down")

        sm.get_secret_value = flaky_get
        sm.put_fail_mode = "raise_no_store"
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            PP._populate_db_secret(sm, SECRET_RUNTIME, "runtime",
                                   RT_USER, self.config())
        self.assertEqual(sm.count("put_secret_value"), 1)


class ScopingAndPartialTests(EnvHarness):
    def _seed_initial(self, sm):
        runtime = json.dumps({"username": RT_USER, "password": RT_PW},
                             sort_keys=True, separators=(',', ':'))
        migration = json.dumps({"username": MG_USER,
                                "password": MG_PW},
                               sort_keys=True, separators=(',', ':'))
        self.seed_all(sm, runtime_value=runtime,
                      migration_value=migration, tls_value=None)

    def test_populate_scopes_exactly_with_no_master_value(self):
        sm, acm = FakeSM(), FakeACM()
        self._seed_initial(sm)
        acm.export_fail = True
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(sm.count_for("describe_secret",
                                      SECRET_MASTER), 1)
        self.assertEqual(sm.count_for("get_secret_value",
                                      SECRET_MASTER), 0)
        self.assertEqual(sm.count_for("put_secret_value",
                                      SECRET_MASTER), 0)
        self.assertEqual(sm.count_for("get_secret_value",
                                      SECRET_RUNTIME), 1)
        self.assertEqual(sm.count_for("get_secret_value",
                                      SECRET_MIGRATION), 1)
        self.assertEqual(sm.count_for("put_secret_value",
                                      SECRET_RUNTIME), 1)
        self.assertEqual(sm.count_for("put_secret_value",
                                      SECRET_MIGRATION), 1)
        self.assertEqual(acm.count("export_certificate"), 1)

    def test_partial_resume_preserves_success_without_rotation(self):
        sm, acm = FakeSM(), FakeACM()
        self._seed_initial(sm)
        acm.export_fail = True
        _code, _text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        runtime_version = sm.store[SECRET_RUNTIME]["VersionId"]
        migration_version = sm.store[SECRET_MIGRATION]["VersionId"]
        sm2_calls_before = len(sm.calls)
        _code2, _text2, exc2 = self.capture(
            PP.do_populate, {"sts": FakeSTS(), "sm": sm, "acm": acm})
        self.assertIsInstance(exc2, ValueError)
        self.assertEqual(sm.store[SECRET_RUNTIME]["VersionId"],
                         runtime_version)
        self.assertEqual(sm.store[SECRET_MIGRATION]["VersionId"],
                         migration_version)
        new_puts = [call for call in sm.calls[sm2_calls_before:]
                    if call[0] == "put_secret_value"]
        self.assertEqual(new_puts, [])

    def test_generic_get_error_is_not_empty(self):
        sm = FakeSM()
        sm.seed(SECRET_TLS, "launchcrew-tls")

        def bad_get(SecretId=""):
            raise FakeClientError("InternalError", "boom")

        sm.get_secret_value = bad_get
        with self.assertRaisesRegex(ValueError, "get failed"):
            PP._get_secret_string(sm, SECRET_TLS, "tls")


class ReadonlyTests(EnvHarness):
    def test_verify_makes_zero_put_and_export_on_failure(self):
        os.environ["LAUNCHCREW_EXPECTED_ROLE"] = "VerifyTaskRole"
        sm, acm = FakeSM(), FakeACM()
        runtime = json.dumps({"username": RT_USER, "password": RT_PW},
                             sort_keys=True, separators=(',', ':'))
        self.seed_all(sm, runtime_value=runtime,
                      migration_value=None, tls_value=None)
        sts = FakeSTS(role="VerifyTaskRole")
        _code, _text, exc = self.capture(
            PP.do_verify_material,
            {"sts": sts, "sm": sm, "acm": acm})
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(sm.count("put_secret_value"), 0)
        self.assertEqual(acm.count("export_certificate"), 0)
        self.assertEqual(sm.count_for("describe_secret",
                                      SECRET_MASTER), 0)
        self.assertEqual(sm.count_for("get_secret_value",
                                      SECRET_MASTER), 0)

    def test_verify_never_touches_master_metadata(self):
        os.environ["LAUNCHCREW_EXPECTED_ROLE"] = "VerifyTaskRole"
        sm, acm = FakeSM(), FakeACM()
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string="x")
        sm.seed(SECRET_MIGRATION, "launchcrew-migration",
                secret_string="y")
        sm.seed(SECRET_TLS, "launchcrew-tls")
        sts = FakeSTS(role="VerifyTaskRole")
        _code, _text, exc = self.capture(
            PP.do_verify_material,
            {"sts": sts, "sm": sm, "acm": acm})
        self.assertIsInstance(exc, ValueError)
        for name, kw in sm.calls:
            self.assertNotEqual(kw.get("SecretId"), SECRET_MASTER)
        self.assertEqual(sm.count("put_secret_value"), 0)
        self.assertEqual(acm.count("export_certificate"), 0)

    def test_verify_wrong_caller_makes_zero_value_calls(self):
        os.environ["LAUNCHCREW_EXPECTED_ROLE"] = "VerifyTaskRole"
        sm, acm = FakeSM(), FakeACM()
        sts = FakeSTS(role="OtherRole")
        _code, _text, exc = self.capture(
            PP.do_verify_material,
            {"sts": sts, "sm": sm, "acm": acm})
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(sm.count("get_secret_value"), 0)
        self.assertEqual(sm.count("put_secret_value"), 0)
        self.assertEqual(acm.count("export_certificate"), 0)


class PrivacyTests(EnvHarness):
    def test_failure_output_never_prints_password_or_url(self):
        sm, acm = FakeSM(), FakeACM()
        runtime = json.dumps({"username": "wrong_user",
                              "password": RT_PW},
                             sort_keys=True, separators=(',', ':'))
        migration = json.dumps({"username": MG_USER,
                                "password": MG_PW},
                               sort_keys=True, separators=(',', ':'))
        self.seed_all(sm, runtime_value=runtime,
                      migration_value=migration, tls_value=None)
        code, text, exc = self.capture(
            PP.do_populate, self.make_clients(sm=sm, acm=acm))
        self.assertIsInstance(exc, ValueError)
        self.assertNotIn(RT_PW, text)
        self.assertNotIn(MG_PW, text)
        self.assertNotIn("postgresql://", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("ResourceNotFoundException", text)

    def test_config_failure_never_prints_secret_values(self):
        os.environ["LAUNCHCREW_DB_HOST"] = "localhost"
        sm, acm = FakeSM(), FakeACM()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = PP.main(["populate_prereqs.py", "--populate"])
        text = out.getvalue()
        self.assertEqual(code, 1)
        self.assertNotIn(RT_PW, text)
        self.assertNotIn("postgresql://", text)
        self.assertIn("populate-prereqs: FAIL:", text)

    def test_usage_lists_modes_without_secrets(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = PP.main(["populate_prereqs.py"])
        self.assertEqual(code, 2)
        text = out.getvalue()
        self.assertIn("--populate", text)
        self.assertIn("--verify-material", text)
        self.assertNotIn(RT_PW, text)


class BoundsTests(EnvHarness):
    def test_oversize_secret_value_refuses(self):
        sm = FakeSM()
        big = "x" * (PP.SECRET_LIMIT_BYTES + 1)
        sm.seed(SECRET_RUNTIME, "launchcrew-runtime",
                secret_string=big, version="v-big")
        with self.assertRaisesRegex(ValueError, "size bound"):
            PP._get_secret_string(sm, SECRET_RUNTIME, "runtime")

    def test_oversize_canonical_payload_refuses(self):
        payload = {"username": RT_USER, "password": "x" * 70000,
                   "database-url": "postgresql://x"}
        with self.assertRaisesRegex(ValueError, "size bound"):
            PP._canonical_secret_string(payload)

    def test_empty_password_refuses(self):
        with self.assertRaises(ValueError):
            PP._build_canonical_db_url(RT_USER, "", DB_HOST, 5432,
                                       "launchcrew")


@unittest.skipUnless(HAS_CRYPTO, "requires deploy-only cryptography, "
                     "host installs isolated lock after terminal")
class TlsCryptoScopingTests(EnvHarness):
    @classmethod
    def setUpClass(cls):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        now = datetime.datetime.now(datetime.timezone.utc)
        ca_key = rsa.generate_private_key(public_exponent=65537,
                                          key_size=2048)
        ca_name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
        ca_cert = (x509.CertificateBuilder()
                   .subject_name(ca_name).issuer_name(ca_name)
                   .public_key(ca_key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(now - datetime.timedelta(days=1))
                   .not_valid_after(now + datetime.timedelta(days=365))
                   .add_extension(x509.BasicConstraints(ca=True,
                                                        path_length=0),
                                  critical=True)
                   .sign(ca_key, hashes.SHA256()))
        leaf_key = rsa.generate_private_key(public_exponent=65537,
                                            key_size=2048)
        leaf_cert = (x509.CertificateBuilder()
                     .subject_name(x509.Name([x509.NameAttribute(
                         NameOID.COMMON_NAME, DOMAIN)]))
                     .issuer_name(ca_name)
                     .public_key(leaf_key.public_key())
                     .serial_number(0x12AB34CD)
                     .not_valid_before(
                         now - datetime.timedelta(days=1))
                     .not_valid_after(
                         now + datetime.timedelta(days=335))
                     .add_extension(x509.SubjectAlternativeName(
                         [x509.DNSName(DOMAIN)]), critical=False)
                     .sign(ca_key, hashes.SHA256()))
        leaf_pem = leaf_cert.public_bytes(
            serialization.Encoding.PEM).decode("ascii")
        chain_pem = ca_cert.public_bytes(
            serialization.Encoding.PEM).decode("ascii")
        encrypted = leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b"test-phrase-1"))
        cls.leaf_pem = leaf_pem
        cls.chain_pem = chain_pem
        cls.encrypted_pem = encrypted.decode("ascii")
        cls.leaf_key = leaf_key
        cls.now = now

    def _seed_db(self, sm):
        runtime = json.dumps({"username": RT_USER, "password": RT_PW},
                             sort_keys=True, separators=(',', ':'))
        migration = json.dumps({"username": MG_USER,
                                "password": MG_PW},
                               sort_keys=True, separators=(',', ':'))
        self.seed_all(sm, runtime_value=runtime,
                      migration_value=migration, tls_value=None)

    def test_existing_tls_reuses_with_zero_export(self):
        from cryptography.hazmat.primitives import serialization
        sm, acm = FakeSM(), FakeACM(serial="12AB34CD", now=self.now)
        self._seed_db(sm)
        cert_bundle = self.leaf_pem + self.chain_pem
        key_pem = self.leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()).decode("ascii")
        tls_payload = PP._canonical_secret_string({
            "tls-cert-b64": base64.b64encode(
                cert_bundle.encode("ascii")).decode("ascii"),
            "tls-key-b64": base64.b64encode(
                key_pem.encode("ascii")).decode("ascii")})
        sm.store[SECRET_TLS]["SecretString"] = tls_payload
        sm.store[SECRET_TLS]["VersionId"] = "v-tls-1"
        acm.leaf_pem = self.leaf_pem
        acm.chain_pem = self.chain_pem
        code, text, exc = self.capture(
            PP.do_populate,
            self.make_clients(sm=sm, acm=acm), self.now)
        self.assertIsNone(exc)
        self.assertEqual(code, 0)
        self.assertEqual(acm.count("export_certificate"), 0)
        self.assertEqual(acm.count("get_certificate"), 1)
        self.assertEqual(sm.count_for("put_secret_value",
                                      SECRET_TLS), 0)
        self.assertNotIn("BEGIN PRIVATE KEY", text)
        self.assertNotIn(RT_PW, text)

    def test_tls_empty_exports_once_with_scoped_calls(self):
        sm = FakeSM()
        acm = FakeACM(serial="12AB34CD", now=self.now)
        self._seed_db(sm)
        acm.leaf_pem = self.leaf_pem
        acm.chain_pem = self.chain_pem
        acm.encrypted_key_pem = self.encrypted_pem
        real_generate = PP._generate_passphrase
        PP._generate_passphrase = lambda length=32: "test-phrase-1"
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.serialization import (
                BestAvailableEncryption)
            re_encrypted = self.leaf_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                BestAvailableEncryption(b"test-phrase-1"))
            acm.encrypted_key_pem = re_encrypted.decode("ascii")
            code, text, exc = self.capture(
                PP.do_populate,
                self.make_clients(sm=sm, acm=acm), self.now)
        finally:
            PP._generate_passphrase = real_generate
        self.assertIsNone(exc)
        self.assertEqual(code, 0)
        self.assertEqual(acm.count("export_certificate"), 1)
        self.assertEqual(sm.count_for("put_secret_value",
                                      SECRET_TLS), 1)
        self.assertEqual(sm.count_for("get_secret_value",
                                      SECRET_MASTER), 0)
        self.assertNotIn("BEGIN PRIVATE KEY", text)
        self.assertNotIn("test-phrase-1", text)

    def test_tls_drift_refuses_without_export_or_put(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        sm, acm = FakeSM(), FakeACM(serial="12AB34CD", now=self.now)
        self._seed_db(sm)
        other_key = rsa.generate_private_key(public_exponent=65537,
                                             key_size=2048)
        key_pem = other_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()).decode("ascii")
        cert_bundle = self.leaf_pem + self.chain_pem
        tls_payload = PP._canonical_secret_string({
            "tls-cert-b64": base64.b64encode(
                cert_bundle.encode("ascii")).decode("ascii"),
            "tls-key-b64": base64.b64encode(
                key_pem.encode("ascii")).decode("ascii")})
        sm.store[SECRET_TLS]["SecretString"] = tls_payload
        sm.store[SECRET_TLS]["VersionId"] = "v-tls-1"
        acm.leaf_pem = self.leaf_pem
        acm.chain_pem = self.chain_pem
        _code, _text, exc = self.capture(
            PP.do_populate,
            self.make_clients(sm=sm, acm=acm), self.now)
        self.assertIsInstance(exc, ValueError)
        self.assertEqual(acm.count("export_certificate"), 0)
        self.assertEqual(sm.count_for("put_secret_value",
                                      SECRET_TLS), 0)

    def test_verify_success_makes_zero_put_and_export(self):
        os.environ["LAUNCHCREW_EXPECTED_ROLE"] = "VerifyTaskRole"
        from cryptography.hazmat.primitives import serialization
        sm = FakeSM()
        acm = FakeACM(serial="12AB34CD", now=self.now)
        config = PP._load_config()
        runtime_url = PP._build_canonical_db_url(
            RT_USER, RT_PW, config["host"], config["port"],
            config["dbname"])
        migration_url = PP._build_canonical_db_url(
            MG_USER, MG_PW, config["host"], config["port"],
            config["dbname"])
        runtime_json = PP._canonical_secret_string(
            {"database-url": runtime_url, "password": RT_PW,
             "username": RT_USER})
        migration_json = PP._canonical_secret_string(
            {"database-url": migration_url, "password": MG_PW,
             "username": MG_USER})
        cert_bundle = self.leaf_pem + self.chain_pem
        key_pem = self.leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()).decode("ascii")
        tls_json = PP._canonical_secret_string({
            "tls-cert-b64": base64.b64encode(
                cert_bundle.encode("ascii")).decode("ascii"),
            "tls-key-b64": base64.b64encode(
                key_pem.encode("ascii")).decode("ascii")})
        self.seed_all(sm, runtime_value=runtime_json,
                      migration_value=migration_json,
                      tls_value=tls_json, tls_version="v-tls-1")
        acm.leaf_pem = self.leaf_pem
        acm.chain_pem = self.chain_pem
        sts = FakeSTS(role="VerifyTaskRole")
        code, text, exc = self.capture(
            PP.do_verify_material,
            {"sts": sts, "sm": sm, "acm": acm}, self.now)
        self.assertIsNone(exc)
        self.assertEqual(code, 0)
        self.assertEqual(sm.count("put_secret_value"), 0)
        self.assertEqual(acm.count("export_certificate"), 0)
        self.assertNotIn(RT_PW, text)
        self.assertNotIn("BEGIN PRIVATE KEY", text)

    def _leading_zero_material(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        now = self.now
        ca_key = rsa.generate_private_key(public_exponent=65537,
                                          key_size=2048)
        ca_name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME,
                                "synthetic-serial-ca")])
        ca_cert = (x509.CertificateBuilder()
                   .subject_name(ca_name).issuer_name(ca_name)
                   .public_key(ca_key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(now - datetime.timedelta(days=1))
                   .not_valid_after(now + datetime.timedelta(days=365))
                   .add_extension(x509.BasicConstraints(ca=True,
                                                        path_length=0),
                                  critical=True)
                   .sign(ca_key, hashes.SHA256()))
        leaf_key = rsa.generate_private_key(public_exponent=65537,
                                            key_size=2048)
        leaf_cert = (x509.CertificateBuilder()
                     .subject_name(x509.Name([x509.NameAttribute(
                         NameOID.COMMON_NAME, DOMAIN)]))
                     .issuer_name(ca_name)
                     .public_key(leaf_key.public_key())
                     .serial_number(0x0A12)
                     .not_valid_before(
                         now - datetime.timedelta(days=1))
                     .not_valid_after(
                         now + datetime.timedelta(days=335))
                     .add_extension(x509.SubjectAlternativeName(
                         [x509.DNSName(DOMAIN)]), critical=False)
                     .sign(ca_key, hashes.SHA256()))
        leaf_pem = leaf_cert.public_bytes(
            serialization.Encoding.PEM).decode("ascii")
        chain_pem = ca_cert.public_bytes(
            serialization.Encoding.PEM).decode("ascii")
        key_pem = leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()).decode("ascii")
        return leaf_pem, chain_pem, key_pem

    def test_leading_zero_serial_reuses_with_colon_form(self):
        sm = FakeSM()
        acm = FakeACM(serial="0A:12", now=self.now)
        self._seed_db(sm)
        leaf_pem, chain_pem, key_pem = self._leading_zero_material()
        tls_payload = PP._canonical_secret_string({
            "tls-cert-b64": base64.b64encode(
                (leaf_pem + chain_pem).encode("ascii")).decode("ascii"),
            "tls-key-b64": base64.b64encode(
                key_pem.encode("ascii")).decode("ascii")})
        sm.store[SECRET_TLS]["SecretString"] = tls_payload
        sm.store[SECRET_TLS]["VersionId"] = "v-tls-1"
        acm.leaf_pem = leaf_pem
        acm.chain_pem = chain_pem
        code, text, exc = self.capture(
            PP.do_populate,
            self.make_clients(sm=sm, acm=acm), self.now)
        self.assertIsNone(exc)
        self.assertEqual(code, 0)
        self.assertEqual(acm.count("export_certificate"), 0)
        self.assertEqual(acm.count("get_certificate"), 1)
        self.assertEqual(sm.count_for("put_secret_value",
                                      SECRET_TLS), 0)
        self.assertNotIn("BEGIN PRIVATE KEY", text)

    def test_leading_zero_serial_verifies_with_colon_form(self):
        os.environ["LAUNCHCREW_EXPECTED_ROLE"] = "VerifyTaskRole"
        from cryptography.hazmat.primitives import serialization  # noqa: F401
        sm = FakeSM()
        acm = FakeACM(serial="0A:12", now=self.now)
        config = PP._load_config()
        runtime_url = PP._build_canonical_db_url(
            RT_USER, RT_PW, config["host"], config["port"],
            config["dbname"])
        migration_url = PP._build_canonical_db_url(
            MG_USER, MG_PW, config["host"], config["port"],
            config["dbname"])
        runtime_json = PP._canonical_secret_string(
            {"database-url": runtime_url, "password": RT_PW,
             "username": RT_USER})
        migration_json = PP._canonical_secret_string(
            {"database-url": migration_url, "password": MG_PW,
             "username": MG_USER})
        leaf_pem, chain_pem, key_pem = self._leading_zero_material()
        tls_json = PP._canonical_secret_string({
            "tls-cert-b64": base64.b64encode(
                (leaf_pem + chain_pem).encode("ascii")).decode("ascii"),
            "tls-key-b64": base64.b64encode(
                key_pem.encode("ascii")).decode("ascii")})
        self.seed_all(sm, runtime_value=runtime_json,
                      migration_value=migration_json,
                      tls_value=tls_json, tls_version="v-tls-1")
        acm.leaf_pem = leaf_pem
        acm.chain_pem = chain_pem
        sts = FakeSTS(role="VerifyTaskRole")
        code, _text, exc = self.capture(
            PP.do_verify_material,
            {"sts": sts, "sm": sm, "acm": acm}, self.now)
        self.assertIsNone(exc)
        self.assertEqual(code, 0)
        self.assertEqual(sm.count("put_secret_value"), 0)
        self.assertEqual(acm.count("export_certificate"), 0)

    def test_malformed_acm_serial_refuses_without_put_or_export(self):
        from cryptography.hazmat.primitives import serialization
        sm = FakeSM()
        acm = FakeACM(serial="ZZ:ZZ", now=self.now)
        self._seed_db(sm)
        key_pem = self.leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()).decode("ascii")
        tls_payload = PP._canonical_secret_string({
            "tls-cert-b64": base64.b64encode(
                (self.leaf_pem + self.chain_pem).encode("ascii")).decode(
                    "ascii"),
            "tls-key-b64": base64.b64encode(
                key_pem.encode("ascii")).decode("ascii")})
        sm.store[SECRET_TLS]["SecretString"] = tls_payload
        sm.store[SECRET_TLS]["VersionId"] = "v-tls-1"
        acm.leaf_pem = self.leaf_pem
        acm.chain_pem = self.chain_pem
        _code, _text, exc = self.capture(
            PP.do_populate,
            self.make_clients(sm=sm, acm=acm), self.now)
        self.assertIsInstance(exc, ValueError)
        self.assertIn("serial", str(exc))
        self.assertEqual(acm.count("export_certificate"), 0)
        self.assertEqual(sm.count_for("put_secret_value",
                                      SECRET_TLS), 0)


class SerialParserTests(unittest.TestCase):
    def test_colon_and_case_forms_parse_to_same_int(self):
        self.assertEqual(PP._parse_acm_serial_to_int("0A:12"), 0x0A12)
        self.assertEqual(PP._parse_acm_serial_to_int("0a:12"), 0x0A12)
        self.assertEqual(PP._parse_acm_serial_to_int("0A12"), 0x0A12)
        self.assertEqual(PP._parse_acm_serial_to_int("12AB34CD"),
                         0x12AB34CD)

    def test_malformed_and_out_of_bounds_serials_refuse(self):
        for bad in ("", "   ", "ZZ:ZZ", "0x", "GG", "12:34:ZZ",
                    "0", "00:00", "F" * 41):
            with self.assertRaises(ValueError, msg=bad):
                PP._parse_acm_serial_to_int(bad)


if __name__ == "__main__":
    unittest.main()
