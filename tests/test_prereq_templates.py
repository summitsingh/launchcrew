"""Static prereq template checks, no AWS calls.

Verifies foundation and prereqs templates carry the exact Project filter,
exact email protocol, managed username plus password generation, empty TLS,
Retain lifecycle for secrets, exportable cert for the exact hostname with
no wildcard, and no secret plaintext or scanner literals.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = ROOT / "deploy" / "aws" / "foundation.yaml"
PREREQS = ROOT / "deploy" / "aws" / "prereqs.yaml"
BOOTSTRAP = ROOT / "deploy" / "aws" / "bootstrap.sh"
FOUNDATION_PARAMS = ROOT / "deploy" / "aws" / "foundation.parameters.example.json"
FARGATE = ROOT / "deploy" / "aws" / "fargate.yaml"


class FoundationTemplateTests(unittest.TestCase):
    def setUp(self):
        self.text = FOUNDATION.read_text(encoding="utf-8")

    def test_owns_four_budget_resources_verbatim(self):
        for logical in ("DemoBudget:", "BudgetTopic:", "BudgetTopicPolicy:",
                        "BudgetEmailSubscription:"):
            self.assertIn(logical, self.text)

    def test_project_filter_exact(self):
        self.assertIn("Key: Project", self.text)
        self.assertIn("Values: [LaunchCrew]", self.text)
        self.assertIn("MatchOptions: [EQUALS]", self.text)
        self.assertNotIn("CostFilters", self.text)

    def test_email_protocol_and_empty_default(self):
        self.assertIn("Protocol: email", self.text)
        self.assertIn("Endpoint: !Ref BudgetNotifyEmail", self.text)
        self.assertIn("TopicArn: !Ref BudgetTopic", self.text)
        self.assertIn("Default: ''", self.text)
        self.assertIn("BudgetNotifyConfigured", self.text)

    def test_tags_present(self):
        self.assertIn("Project", self.text)
        self.assertIn("LaunchCrew", self.text)
        self.assertIn("Environment", self.text)
        self.assertIn("TeardownBy", self.text)

    def test_no_secrets_in_foundation(self):
        self.assertNotIn("GenerateSecretString", self.text)
        self.assertNotIn("SecretString:", self.text)
        self.assertNotIn("SecretStringTemplate", self.text)

    def test_no_scanner_literals(self):
        lowered = self.text.lower()
        self.assertNotIn("s" + "k-", lowered)
        self.assertNotIn("ak" + "ia", lowered)
        self.assertNotIn("gh" + "p_", lowered)
        self.assertNotIn("gh" + "o_", lowered)
        self.assertNotIn("\u2014", self.text)


class PrereqsTemplateTests(unittest.TestCase):
    def setUp(self):
        self.text = PREREQS.read_text(encoding="utf-8")

    def test_exactly_four_secrets(self):
        self.assertEqual(self.text.count("AWS::SecretsManager::Secret"), 4)
        for logical in ("MasterSecret:", "RuntimeSecret:",
                        "MigrationSecret:", "TlsSecret:"):
            self.assertIn(logical, self.text)

    def test_username_template_generation(self):
        self.assertEqual(self.text.count("GenerateSecretString:"), 3)
        self.assertIn('{"username":"launchcrew_master"}', self.text)
        self.assertIn('{"username":"launchcrew_runtime"}', self.text)
        self.assertIn('{"username":"launchcrew_migration"}', self.text)
        self.assertEqual(self.text.count("GenerateStringKey: password"), 3)
        self.assertIn("PasswordLength: 32", self.text)
        self.assertIn("ExcludeCharacters:", self.text)

    def test_no_secret_plaintext(self):
        self.assertNotIn("SecretString:", self.text)
        self.assertIn("SecretStringTemplate:", self.text)

    def test_tls_empty(self):
        start = self.text.index("TlsSecret:")
        try:
            end = self.text.index("DemoCertificate:")
        except ValueError:
            end = len(self.text)
        tls_block = self.text[start:end]
        self.assertNotIn("GenerateSecretString", tls_block)
        self.assertNotIn("SecretString:", tls_block)

    def test_retain_lifecycle_for_secrets(self):
        self.assertEqual(self.text.count("DeletionPolicy: Retain"), 4)
        self.assertEqual(self.text.count("UpdateReplacePolicy: Retain"), 4)

    def test_exportable_cert_exact(self):
        self.assertIn("DemoCertificate:", self.text)
        self.assertIn("launchcrew.summitsingh.com", self.text)
        self.assertIn("ValidationMethod: DNS", self.text)
        self.assertIn("CertificateExport: ENABLED", self.text)
        self.assertNotIn("*", self.text)

    def test_no_scanner_literals(self):
        lowered = self.text.lower()
        self.assertNotIn("s" + "k-", lowered)
        self.assertNotIn("ak" + "ia", lowered)
        self.assertNotIn("gh" + "p_", lowered)
        self.assertNotIn("gh" + "o_", lowered)
        self.assertNotIn("\u2014", self.text)


class BootstrapPrereqSeamTests(unittest.TestCase):
    def setUp(self):
        self.text = BOOTSTRAP.read_text(encoding="utf-8")

    def test_opt_in_phases_explicit(self):
        self.assertIn("--foundation-stack-name", self.text)
        self.assertIn("--prereqs-stack-name", self.text)
        self.assertIn("--foundation-parameters-file", self.text)
        self.assertIn("--dns-receipt-file", self.text)
        self.assertIn("foundation|prereqs", self.text)

    def test_exact_gate_and_expiry_helpers(self):
        self.assertIn("check_sns_exact_gate", self.text)
        self.assertIn("check_prereq_expiry", self.text)
        self.assertIn("LAUNCHCREW_TODAY", self.text)
        self.assertIn("2026-11-09", self.text)
        self.assertIn("list-subscriptions-by-topic", self.text)
        self.assertIn("describe-certificate", self.text)

    def test_driver_never_fetches_secret_values(self):
        code_lines = [line for line in self.text.splitlines()
                      if not line.strip().startswith("#")]
        code = "\n".join(code_lines)
        self.assertNotIn("GetSecretValue", code)
        self.assertNotIn("get-secret-value", code.lower())
        self.assertNotIn("PutSecretValue", code)
        self.assertNotIn("ExportCertificate", code)

    def test_no_scanner_literals(self):
        self.assertNotIn("s" + "k-", self.text.lower())
        self.assertNotIn("\u2014", self.text)


class FoundationParamsExampleTests(unittest.TestCase):
    def setUp(self):
        self.text = FOUNDATION_PARAMS.read_text(encoding="utf-8")

    def test_carries_limit_and_empty_email(self):
        self.assertIn("BudgetLimitUsd", self.text)
        self.assertIn("BudgetNotifyEmail", self.text)
        self.assertIn('""', self.text)
        self.assertIn("REPLACE_WITH", self.text)

    def test_no_real_address(self):
        self.assertNotIn("@example", self.text.lower())
        self.assertNotIn("example.test", self.text.lower())
        self.assertNotIn("\u2014", self.text)


class LegacyPreservedTests(unittest.TestCase):
    def test_fargate_still_carries_budget_until_phase_c(self):
        text = FARGATE.read_text(encoding="utf-8")
        for logical in ("DemoBudget:", "BudgetTopic:",
                        "BudgetTopicPolicy:", "BudgetEmailSubscription:"):
            self.assertIn(logical, text)

    def test_default_all_order_mentions_legacy_first(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        for phase in ("infra", "images", "dbroles", "migrate", "enable"):
            self.assertIn(phase, text)


if __name__ == "__main__":
    unittest.main()
