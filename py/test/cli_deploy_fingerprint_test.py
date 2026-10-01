import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner

from modal.cli._deploy_fingerprint import cache_matches, deployment_fingerprint, save_fingerprint

run_module = importlib.import_module("modal.cli.run")


class FingerprintCacheTests(unittest.TestCase):
    def test_file_changes_and_context_changes_invalidate_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            helper = root / "helper.py"
            cache = root / "cache.json"
            source.write_text("import helper\n", encoding="utf-8")
            helper.write_text("VALUE = 1\n", encoding="utf-8")
            context = {"app": "probe", "environment": "main"}
            first = deployment_fingerprint((source, helper), context)
            save_fingerprint(cache, first)
            self.assertTrue(cache_matches(cache, first))

            helper.write_text("VALUE = 2\n", encoding="utf-8")
            self.assertNotEqual(first, deployment_fingerprint((source, helper), context))
            self.assertNotEqual(first, deployment_fingerprint((source, helper), {"app": "other"}))
            cache.write_text("not json", encoding="utf-8")
            self.assertFalse(cache_matches(cache, first))

    def test_cli_skips_second_deploy_and_redeploys_after_change_or_force(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            helper = root / "helper.py"
            cache = root / "cache.json"
            source.write_text("value = 1\n", encoding="utf-8")
            helper.write_text("HELPER = 1\n", encoding="utf-8")
            args = ["--fingerprint-cache", str(cache), "--fingerprint-input", str(helper), str(source)]

            with (
                patch.object(run_module, "ensure_env", return_value=""),
                patch.object(run_module, "import_app_from_ref", return_value=SimpleNamespace(name="probe")),
                patch.object(run_module, "config", {"token_id": "ak-test", "server_url": "https://api.modal.test"}),
                patch.object(run_module, "deploy_app", return_value=SimpleNamespace(app_id="ap-test")) as deploy,
            ):
                runner = CliRunner()
                first = runner.invoke(run_module.deploy, args)
                second = runner.invoke(run_module.deploy, args)
                source.write_text("value = 2\n", encoding="utf-8")
                changed = runner.invoke(run_module.deploy, args)
                helper.write_text("HELPER = 2\n", encoding="utf-8")
                changed_helper = runner.invoke(run_module.deploy, args)
                forced = runner.invoke(run_module.deploy, ["--force-deploy", *args])

            for result in (first, second, changed, changed_helper, forced):
                self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("no deployment API call", second.output)
            self.assertEqual(deploy.call_count, 4)

    def test_cache_path_cannot_overwrite_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.py"
            source.write_text("value = 1\n", encoding="utf-8")
            with (
                patch.object(run_module, "ensure_env", return_value=""),
                patch.object(run_module, "import_app_from_ref", return_value=SimpleNamespace(name="probe")),
                patch.object(run_module, "deploy_app") as deploy,
            ):
                result = CliRunner().invoke(run_module.deploy, ["--fingerprint-cache", str(source), str(source)])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("cannot overwrite", result.output)
            self.assertEqual(source.read_text(encoding="utf-8"), "value = 1\n")
            deploy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
