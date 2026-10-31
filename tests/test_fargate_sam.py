"""SAM flag plus web public assets: static wiring checks.

No test contacts AWS. Verifies the ApiTaskDefinition container api
carries LAUNCHCREW_PHOTO_SAM_ENABLED true, and the web runtime image
copies Next.js public assets so standalone serving includes web/public
files such as sitemap.xml, favicon.ico, and facts/demo_facts.json.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FARGATE = ROOT / "deploy" / "aws" / "fargate.yaml"
CONTAINERFILE = ROOT / "containers" / "web.Containerfile"


class FargateSamTests(unittest.TestCase):
    def setUp(self):
        self.text = FARGATE.read_text(encoding="utf-8")

    def test_sam_enabled_in_api_environment(self):
        self.assertIn(
            "{ Name: LAUNCHCREW_PHOTO_SAM_ENABLED, Value: 'true' }",
            self.text,
        )

    def test_sam_enabled_under_api_task_container_api(self):
        api_start = self.text.index("ApiTaskDefinition:")
        api_block = self.text[api_start:self.text.index("WebTaskDefinition:")]
        container_start = api_block.index("- Name: api")
        container_block = api_block[container_start:]
        env_start = container_block.index("Environment:")
        secrets_start = container_block.index("Secrets: !If")
        env_block = container_block[env_start:secrets_start]
        self.assertIn(
            "{ Name: LAUNCHCREW_PHOTO_SAM_ENABLED, Value: 'true' }",
            env_block,
        )


class WebPublicAssetTests(unittest.TestCase):
    def setUp(self):
        self.text = CONTAINERFILE.read_text(encoding="utf-8")

    def test_public_dir_copied_to_runtime(self):
        self.assertIn(
            "COPY --from=build --chown=node:node /app/public ./public",
            self.text,
        )

    def test_public_copy_after_workdir_in_final_stage(self):
        final_stage = self.text.split("FROM docker.io/library/node:22-alpine")[-1]
        self.assertIn("WORKDIR /app", final_stage)
        self.assertIn("ENV NODE_ENV=production", final_stage)
        workdir_pos = final_stage.index("WORKDIR /app")
        copy_pos = final_stage.index(
            "COPY --from=build --chown=node:node /app/public ./public"
        )
        self.assertGreater(copy_pos, workdir_pos)


if __name__ == "__main__":
    unittest.main()
