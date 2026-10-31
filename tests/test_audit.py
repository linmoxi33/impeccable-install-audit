#!/usr/bin/env python3
"""Behavioural tests for impeccable-install-audit (stdlib unittest only)."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "impeccable-install-audit"
GOOD = b"engine-bytes-good\n" * 8
DRIFT = b"engine-bytes-drift\n" * 8
GOOD_SHA = hashlib.sha256(GOOD).hexdigest()


def run(args, cwd=None):
    proc = subprocess.run([sys.executable, str(CLI)] + args, capture_output=True,
                          text=True, cwd=cwd or ROOT)
    return proc


class Fixture:
    """Build a throwaway tree with Impeccable installs."""

    def __init__(self, tmp):
        self.root = Path(tmp)

    def install(self, harness, skill_version="4.8.0", engine_version="0.1.18",
                blob=GOOD, launcher=True, checksums=True, pin=GOOD_SHA):
        d = self.root / harness / "skills" / "impeccable"
        (d / "scripts" / "bin" / "linux-x64").mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: impeccable\nversion: {skill_version}\n---\n", encoding="utf-8")
        (d / "scripts" / "VERSION").write_text(engine_version + "\n", encoding="utf-8")
        (d / "scripts" / "bin" / "linux-x64" / "impeccable").write_bytes(blob)
        if launcher:
            (d / "scripts" / "impeccable").write_text("#!/bin/sh\n", encoding="utf-8")
        if checksums:
            (d / "scripts" / "engine-checksums.txt").write_text(
                f"0.1.18 impeccable-linux-x64 {pin}\n", encoding="utf-8")
        return d

    def hook(self, rel, command):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"hooks": {"X": [{"command": command}]}}), encoding="utf-8")
        return p


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def audit(self, *extra):
        return run([self.tmp.name, "--json", "--min-engine-bytes", "16"] + list(extra))

    def rules(self, proc):
        return {f["rule"] for f in json.loads(proc.stdout)["findings"]}

    # --- behaviour: exit codes + findings ---------------------------------
    def test_clean_tree_exits_zero(self):
        self.fx.install(".claude")
        proc = self.audit()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["ok"])

    def test_version_drift_exits_one(self):
        self.fx.install(".claude", skill_version="4.8.0")
        self.fx.install(".agents", skill_version="4.7.0")
        proc = self.audit()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("version-drift", self.rules(proc))

    def test_checksum_mismatch_detected(self):
        self.fx.install(".claude", blob=DRIFT)
        proc = self.audit()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("checksum-mismatch", self.rules(proc))

    def test_duplicate_engine_detected(self):
        self.fx.install(".claude")
        self.fx.install(".agents")
        proc = self.audit()
        self.assertIn("duplicate-engine", self.rules(proc))

    def test_engine_pin_mismatch_against_checksums(self):
        self.fx.install(".claude", engine_version="0.1.17")
        proc = self.audit()
        self.assertIn("engine-pin-mismatch", self.rules(proc))

    def test_missing_engine_without_cache(self):
        d = self.fx.install(".claude")
        (d / "scripts" / "bin" / "linux-x64" / "impeccable").unlink()
        proc = self.audit()
        self.assertIn("missing-engine", self.rules(proc))

    def test_hook_target_missing(self):
        self.fx.install(".claude")
        self.fx.hook(".codex/hooks.json",
                     "~/.agents/skills/impeccable/scripts/impeccable context")
        proc = self.audit()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("hook-target-missing", self.rules(proc))

    def test_hook_target_present_is_clean(self):
        d = self.fx.install(".claude")
        launcher = d / "scripts" / "impeccable"
        self.fx.hook(".codex/hooks.json", f"{launcher} context")
        proc = self.audit()
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_version_unreadable_is_warning_not_error(self):
        d = self.fx.install(".claude")
        (d / "SKILL.md").write_text("# no frontmatter\n", encoding="utf-8")
        proc = self.audit()
        report = json.loads(proc.stdout)
        self.assertEqual(report["summary"]["warnings"], 1)
        self.assertEqual(report["summary"]["errors"], 0)
        self.assertEqual(proc.returncode, 0)

    # --- behaviour: usage / input errors ---------------------------------
    def test_missing_root_exits_two(self):
        proc = run([str(Path(self.tmp.name) / "nope")])
        self.assertEqual(proc.returncode, 2)

    def test_no_installs_exits_two(self):
        (Path(self.tmp.name) / "empty").mkdir()
        proc = self.audit()
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)["error"], "no-installs")

    # --- behaviour: output contract ---------------------------------------
    def test_json_is_parseable_and_schema_stable(self):
        self.fx.install(".claude")
        proc = self.audit()
        report = json.loads(proc.stdout)
        self.assertEqual(report["schema"], "impeccable-install-audit/1")
        self.assertEqual(report["summary"]["installs"], 1)
        self.assertIn("path", report["installs"][0])
        self.assertIn("harness", report["installs"][0])

    def test_human_output_lists_installs(self):
        self.fx.install(".claude")
        proc = run([self.tmp.name])
        self.assertEqual(proc.returncode, 0)
        self.assertIn(".claude", proc.stdout)
        self.assertIn("1 install(s)", proc.stdout)

    def test_example_fixture_matches_committed_report(self):
        expected = json.loads((ROOT / "examples" / "out" / "report.json").read_text())
        proc = run(["examples/in", "--json", "--min-engine-bytes", "32"], cwd=ROOT)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
