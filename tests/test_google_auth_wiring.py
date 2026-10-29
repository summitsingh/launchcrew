"""Google-only CloudFormation wiring: conditional injection and least privilege.

Static checks only, no AWS calls. Verifies template defaults stay keyless,
Google secret injection is conditional on explicit enable plus exact ARN,
IAM grants scope to that exact secret with no wildcard, PUBLIC_BASE_URL is
exact HTTPS, and no Meta or Facebook wiring is present. No secret values.
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FARGATE = ROOT / "deploy" / "aws" / "fargate.yaml"
PARAMS = ROOT / "deploy" / "aws" / "parameters.example.json"
BOOTSTRAP = ROOT / "deploy" / "aws" / "bootstrap.sh"


class GoogleTemplateTests(unittest.TestCase):
    def setUp(self):
        self.text = FARGATE.read_text(encoding="utf-8")

    def test_enable_defaults_off(self):
        self.assertIn("EnableGoogleAuth:", self.text)
        self.assertIn("Default: 'false'", self.text)
        self.assertIn("AllowedValues: ['true', 'false']", self.text)
        self.assertIn("GoogleOAuthSecretArn:", self.text)
        self.assertIn("Default: ''", self.text)

    def test_condition_requires_enable_and_exact_arn(self):
        self.assertIn("GoogleAuthEnabled:", self.text)
        self.assertIn("!And [!Equals ['true', !Ref EnableGoogleAuth]", self.text)
        self.assertIn("!Not [!Equals ['', !Ref GoogleOAuthSecretArn]]", self.text)

    def test_rule_refuses_enable_true_with_empty_arn(self):
        self.assertIn("Rules:", self.text)
        self.assertIn("GoogleAuthRequiresSecret:", self.text)
        self.assertIn("RuleCondition: !Equals ['true', !Ref EnableGoogleAuth]", self.text)
        self.assertIn("Assert: !Not [!Equals ['', !Ref GoogleOAuthSecretArn]]", self.text)
        self.assertIn("empty refused before any mutation", self.text)

    def test_public_base_url_exact_https(self):
        self.assertIn("PUBLIC_BASE_URL, Value: 'https://launchcrew.summitsingh.com'", self.text)
        self.assertNotIn("http://launchcrew", self.text)
        self.assertNotIn("https://launchcrew.summitsingh.com/", self.text)

    def test_auth_enabled_conditional_not_hardcoded_true(self):
        self.assertIn("AUTH_ENABLED, Value: !If [GoogleAuthEnabled, 'true', 'false']", self.text)
        api_start = self.text.index("ApiTaskDefinition:")
        api_block = self.text[api_start:self.text.index("WebTaskDefinition:")]
        self.assertNotIn("AUTH_ENABLED, Value: 'true'", api_block)

    def test_secrets_conditional_google_only(self):
        api_start = self.text.index("ApiTaskDefinition:")
        api_block = self.text[api_start:self.text.index("WebTaskDefinition:")]
        self.assertIn("Secrets: !If", api_block)
        self.assertIn("GoogleAuthEnabled", api_block)
        self.assertIn("GOOGLE_CLIENT_ID, ValueFrom: !Sub '${GoogleOAuthSecretArn}:google-client-id::'", api_block)
        self.assertIn("GOOGLE_CLIENT_SECRET, ValueFrom: !Sub '${GoogleOAuthSecretArn}:google-client-secret::'", api_block)
        self.assertNotIn("FACEBOOK_CLIENT", api_block)
        self.assertNotIn("Facebook", api_block)
        self.assertNotIn("META_API_KEY", api_block)
        self.assertNotIn("MetaSecret", api_block)

    def test_google_policy_least_privilege_exact(self):
        self.assertIn("ApiGoogleAuthPolicy:", self.text)
        start = self.text.index("ApiGoogleAuthPolicy:")
        block = self.text[start:self.text.index("ApiTaskDefinition:")]
        self.assertIn("Condition: GoogleAuthEnabled", block)
        self.assertIn("api-google-auth-secret-only", block)
        self.assertIn("secretsmanager:GetSecretValue", block)
        self.assertIn("Resource: [!Ref GoogleOAuthSecretArn]", block)
        self.assertIn("Roles: [!Ref ApiExecutionRole]", block)
        self.assertNotIn("Resource: '*'", block)
        self.assertNotIn('Resource: "*"', block)
        self.assertNotIn("secretsmanager:PutSecretValue", block)
        self.assertNotIn("kms:", block.lower())
        self.assertNotIn("*", block.split("Resource:")[1].split("\n")[0])

    def test_base_execution_role_unchanged_no_google(self):
        start = self.text.index("ApiExecutionRole:")
        block = self.text[start:self.text.index("ApiTaskRole:")]
        self.assertIn("api-execution-secrets-only", block)
        self.assertIn("!Ref RuntimeDbUrlSecretArn", block)
        self.assertIn("!Ref TlsSecretArn", block)
        self.assertNotIn("GoogleOAuthSecretArn", block)

    def test_no_secret_values_or_wildcards(self):
        self.assertNotIn("apps.googleusercontent.com", self.text)
        self.assertNotIn("Resource: '*'", self.text)
        self.assertNotIn('Resource: "*"', self.text)
        lowered = self.text.lower()
        self.assertNotIn("s" + "k-", lowered)
        self.assertNotIn("ak" + "ia", lowered)
        self.assertNotIn("\u2014", self.text)


class GoogleParamsTests(unittest.TestCase):
    def test_example_carries_google_keys_placeholder_only(self):
        doc = json.loads(PARAMS.read_text(encoding="utf-8"))
        by_key = {entry["ParameterKey"]: entry["ParameterValue"] for entry in doc}
        self.assertEqual(by_key["EnableGoogleAuth"], "false")
        self.assertIn("REPLACE_WITH_GOOGLE_OAUTH_SECRET_ARN", by_key["GoogleOAuthSecretArn"])
        self.assertNotIn("111122223333", by_key["GoogleOAuthSecretArn"])
        self.assertNotIn("apps.googleusercontent.com", PARAMS.read_text(encoding="utf-8"))

    def test_bootstrap_allows_google_secret_key(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn('"GoogleOAuthSecretArn"', text)
        self.assertIn("KNOWN_SECRET_KEYS", text)


if __name__ == "__main__":
    unittest.main()
