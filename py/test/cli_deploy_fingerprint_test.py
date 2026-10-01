import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner

from modal.cli._deploy_fingerprint import cache_matches, deployment_fingerprint, save_fingerprint
from modal.experimental._ast_packaging import reduced_function_sources, sources_digest

run_module = importlib.import_module("modal.cli.run")


def _ast_test_compute(value):
    return value


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

    def test_ast_fingerprint_ignores_unrelated_source_but_tracks_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            helper = root / "helpers.py"
            source.write_text(
                "FACTOR = 2\n"
                "def same_file(value): return value * FACTOR\n"
                "def unrelated(): return 1\n"
                "@ast_function(app, cache_dir='cache')\n"
                "def _ast_test_compute(value):\n"
                "    from helpers import double\n"
                "    return same_file(double(value))\n",
                encoding="utf-8",
            )
            helper.write_text("FACTOR = 2\ndef double(value): return value * FACTOR\n", encoding="utf-8")
            with patch("modal.experimental._ast_packaging.inspect.getsourcefile", return_value=str(source)):
                first = reduced_function_sources(_ast_test_compute)
                source.write_text(source.read_text(encoding="utf-8").replace("return 1", "return 2"), encoding="utf-8")
                unrelated_change = reduced_function_sources(_ast_test_compute)
                helper.write_text("FACTOR = 3\ndef double(value): return value * FACTOR\n", encoding="utf-8")
                helper_change = reduced_function_sources(_ast_test_compute)

            self.assertEqual(set(first), {"app.py", "helpers.py"})
            self.assertIn(b"FACTOR = 2", first["app.py"])
            self.assertIn(b"def same_file", first["app.py"])
            self.assertNotIn(b"unrelated", first["app.py"])
            self.assertNotIn(b"@ast_function", first["app.py"])
            self.assertEqual(sources_digest(first), sources_digest(unrelated_change))
            self.assertNotEqual(sources_digest(first), sources_digest(helper_change))

    def test_ast_artifact_includes_explicit_dynamic_import_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            plugins = root / "plugins"
            plugins.mkdir()
            (plugins / "__init__.py").write_text("", encoding="utf-8")
            (plugins / "one.py").write_text("VALUE = 1\n", encoding="utf-8")
            source.write_text(
                "@ast_function(app, cache_dir='cache')\n"
                "def _ast_test_compute(name):\n"
                "    import importlib\n"
                "    return importlib.import_module('plugins.' + name).VALUE\n",
                encoding="utf-8",
            )
            with patch("modal.experimental._ast_packaging.inspect.getsourcefile", return_value=str(source)):
                omitted = reduced_function_sources(_ast_test_compute)
                included = reduced_function_sources(_ast_test_compute, ("plugins",))

            self.assertEqual(set(omitted), {"app.py"})
            self.assertEqual(set(included), {"app.py", "plugins/__init__.py", "plugins/one.py"})

    def test_cli_ast_fingerprint_uses_artifact_not_entire_source_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            cache = root / "cache.json"
            source.write_text("unrelated = 1\n", encoding="utf-8")
            app = SimpleNamespace(
                name="probe",
                _experimental_ast_fingerprints={"compute": {"artifact": "digest-1", "options": "{}"}},
                _local_state=SimpleNamespace(
                    functions={"compute": object()},
                    classes={},
                    image_default=None,
                    secrets_default=[],
                    volumes_default={},
                    tags={},
                ),
            )
            args = ["--fingerprint-cache", str(cache), str(source)]
            with (
                patch.object(run_module, "ensure_env", return_value=""),
                patch.object(run_module, "import_app_from_ref", return_value=app),
                patch.object(run_module, "config", {"token_id": "ak-test", "server_url": "https://api.modal.test"}),
                patch.object(run_module, "deploy_app", return_value=SimpleNamespace(app_id="ap-test")) as deploy,
            ):
                runner = CliRunner()
                first = runner.invoke(run_module.deploy, args)
                source.write_text("unrelated = 2\n", encoding="utf-8")
                unchanged_artifact = runner.invoke(run_module.deploy, args)
                app._experimental_ast_fingerprints["compute"]["artifact"] = "digest-2"
                changed_artifact = runner.invoke(run_module.deploy, args)

            for result in (first, unchanged_artifact, changed_artifact):
                self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("no deployment API call", unchanged_artifact.output)
            self.assertEqual(deploy.call_count, 2)


if __name__ == "__main__":
    unittest.main()
