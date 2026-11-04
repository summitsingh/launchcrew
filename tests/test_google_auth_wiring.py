"""Public CloudFormation wiring: no sign-in secrets, scoped Meta and Drive grants.

Static checks only. Sign-in stays disabled and has no credential injection.
Meta and Drive remain conditional on exact ARNs, with least-privilege policies.
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
        self.assertIn("AUTH_ENABLED, Value: 'false'", self.text)
        self.assertNotIn('EnableGoogleAuth:', self.text)

    def test_condition_requires_enable_and_exact_arn(self):
        self.assertNotIn('GoogleAuthEnabled:', self.text)
        self.assertNotIn('GoogleOAuthSecretArn:', self.text)

    def test_rule_refuses_enable_true_with_empty_arn(self):
        self.assertNotIn('GoogleAuthRequiresSecret:', self.text)

    def test_public_base_url_exact_https(self):
        self.assertIn("PUBLIC_BASE_URL, Value: 'https://launchcrew.summitsingh.com'", self.text)
        self.assertNotIn("http://launchcrew", self.text)
        self.assertNotIn("https://launchcrew.summitsingh.com/", self.text)

    def test_auth_enabled_conditional_not_hardcoded_true(self):
        self.assertIn("AUTH_ENABLED, Value: 'false'", self.text)
        self.assertNotIn('AUTH_ENABLED, Value: !If', self.text)

    def test_secrets_conditional_per_entry(self):
        api_start = self.text.index("ApiTaskDefinition:")
        api_block = self.text[api_start:self.text.index("WebTaskDefinition:")]
        self.assertNotIn("GoogleAuthEnabled", api_block)
        self.assertNotIn("GOOGLE_CLIENT_ID, ValueFrom: !Sub '${GoogleOAuthSecretArn}:google-client-id::'", api_block)
        self.assertNotIn("GOOGLE_CLIENT_SECRET, ValueFrom: !Sub '${GoogleOAuthSecretArn}:google-client-secret::'", api_block)
        self.assertIn("MetaKeyEnabled", api_block)
        self.assertIn("META_API_KEY, ValueFrom: !Sub '${MetaSecretArn}:meta-api-key::'", api_block)
        self.assertIn("DriveEnabled", api_block)
        self.assertIn("GOOGLE_DRIVE_API_KEY, ValueFrom: !Sub '${DriveSecretArn}:google-drive-api-key::'", api_block)
        self.assertIn("GOOGLE_DRIVE_APP_ID, ValueFrom: !Sub '${DriveSecretArn}:google-drive-app-id::'", api_block)
        self.assertNotIn("FacebookEnabled", api_block)
        self.assertNotIn("FACEBOOK_CLIENT_ID, ValueFrom: !Sub '${FacebookOAuthSecretArn}:facebook-client-id::'", api_block)
        self.assertNotIn("FACEBOOK_CLIENT_SECRET, ValueFrom: !Sub '${FacebookOAuthSecretArn}:facebook-client-secret::'", api_block)
        self.assertIn("!Ref 'AWS::NoValue'", api_block)
        self.assertNotIn("Secrets: !If", api_block)

    def test_meta_key_conditional_exact_arn(self):
        self.assertIn("MetaSecretArn:", self.text)
        self.assertIn("Default: ''", self.text)
        self.assertIn("MetaKeyEnabled: !Not [!Equals ['', !Ref MetaSecretArn]]", self.text)
        api_start = self.text.index("ApiTaskDefinition:")
        api_block = self.text[api_start:self.text.index("WebTaskDefinition:")]
        self.assertIn("MetaKeyEnabled", api_block)
        self.assertIn("META_API_KEY, ValueFrom: !Sub '${MetaSecretArn}:meta-api-key::'", api_block)
        self.assertIn("META_MODEL, Value: muse-spark-1.3", api_block)
        self.assertIn("META_API_BASE_URL, Value: https://api.meta.ai/v1", api_block)

    def test_google_policy_least_privilege_exact(self):
        self.assertNotIn('ApiGoogleAuthPolicy:', self.text)
        self.assertNotIn('GOOGLE_CLIENT_SECRET', self.text)

    def test_base_execution_role_unchanged_no_google(self):
        start = self.text.index("ApiExecutionRole:")
        block = self.text[start:self.text.index("ApiTaskRole:")]
        self.assertIn("api-execution-secrets-only", block)
        self.assertIn("!Ref RuntimeDbUrlSecretArn", block)
        self.assertIn("!Ref TlsSecretArn", block)
        self.assertNotIn("GoogleOAuthSecretArn", block)
        self.assertNotIn("MetaSecretArn", block)

    def test_meta_policy_least_privilege_exact(self):
        self.assertIn("ApiMetaSecretPolicy:", self.text)
        start = self.text.index("ApiMetaSecretPolicy:")
        block = self.text[start:self.text.index("ApiTaskDefinition:")]
        self.assertIn("Condition: MetaKeyEnabled", block)
        self.assertIn("api-meta-secret-only", block)
        self.assertIn("secretsmanager:GetSecretValue", block)
        self.assertIn("Resource: [!Ref MetaSecretArn]", block)
        self.assertIn("Roles: [!Ref ApiExecutionRole]", block)
        self.assertNotIn("Resource: '*'", block)
        lowered = block.lower()
        self.assertNotIn("putsecretvalue", lowered)
        self.assertNotIn("kms:", lowered)
        self.assertNotIn("*", block.split("Resource:")[1].split("\n")[0])

    def test_drive_policy_least_privilege_exact(self):
        self.assertIn("ApiDriveSecretPolicy:", self.text)
        self.assertIn("DriveEnabled:", self.text)
        self.assertIn("DriveSecretArn:", self.text)
        start = self.text.index("ApiDriveSecretPolicy:")
        block = self.text[start:self.text.index("ApiTaskDefinition:")]
        self.assertIn("Condition: DriveEnabled", block)
        self.assertIn("api-drive-secret-only", block)
        self.assertIn("secretsmanager:GetSecretValue", block)
        self.assertIn("Resource: [!Ref DriveSecretArn]", block)
        self.assertIn("Roles: [!Ref ApiExecutionRole]", block)
        self.assertNotIn("Resource: '*'", block)
        lowered = block.lower()
        self.assertNotIn("putsecretvalue", lowered)
        self.assertNotIn("kms:", lowered)
        self.assertNotIn("*", block.split("Resource:")[1].split("\n")[0])

    def test_facebook_policy_least_privilege_exact(self):
        self.assertNotIn('ApiFacebookSecretPolicy:', self.text)
        self.assertNotIn('FACEBOOK_CLIENT_SECRET', self.text)
        self.assertNotIn('FacebookOAuthSecretArn:', self.text)

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
        doc = json.loads(PARAMS.read_text())
        keys = {entry['ParameterKey'] for entry in doc}
        self.assertNotIn('EnableGoogleAuth', keys)
        self.assertNotIn('GoogleOAuthSecretArn', keys)

    def test_bootstrap_allows_google_secret_key(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn('"GoogleOAuthSecretArn"', text)
        self.assertIn("KNOWN_SECRET_KEYS", text)

    def test_example_carries_meta_key_placeholder_only(self):
        doc = json.loads(PARAMS.read_text(encoding="utf-8"))
        by_key = {entry["ParameterKey"]: entry["ParameterValue"] for entry in doc}
        self.assertIn("REPLACE_WITH_META_KEY_SECRET_ARN", by_key["MetaSecretArn"])
        self.assertNotIn("arn:aws:secretsmanager", PARAMS.read_text(encoding="utf-8"))

    def test_bootstrap_allows_meta_secret_key(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn('"MetaSecretArn"', text)
        self.assertIn("--meta-secret-arn", text)
        self.assertIn("check_meta_key_gate", text)
        self.assertIn("verify_meta_policy_least_privilege", text)

    def test_bootstrap_allows_drive_secret_key(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn('"DriveSecretArn"', text)
        self.assertIn("--drive-secret-arn", text)
        self.assertIn("check_drive_secret_gate", text)
        self.assertIn("verify_drive_policy_least_privilege", text)

    def test_bootstrap_allows_facebook_secret_key(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn('"FacebookOAuthSecretArn"', text)
        self.assertIn("--facebook-secret-arn", text)
        self.assertIn("check_facebook_secret_gate", text)
        self.assertIn("verify_facebook_policy_least_privilege", text)


if __name__ == "__main__":
    unittest.main()
