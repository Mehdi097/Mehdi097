"""The pack itself: folders, front-matter, scripts that compile, no leftovers."""

import os
import py_compile
import re
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKILLS = {
    "mt5-core": "bridge.py",
    "mt5-analyst": "analyst.py",
    "mt5-screener": "screen.py",
    "mt5-copycat": "copy.py",
    "mt5-budget": "size.py",
    "mt5-risk": "check.py",
    "mt5-broker": "execute.py",
    "mt5-journal": "journal.py",
    "mt5-alerts": "alerts.py",
    "mt5-exposure": "rebalance.py",
    "mt5-calendar": "econ.py",
    "mt5-news": "news.py",
}


def front_matter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (match.group(1), text) if match else ("", text)


class TestStructure(unittest.TestCase):
    def test_every_skill_folder_exists(self):
        for folder in SKILLS:
            self.assertTrue(os.path.isdir(os.path.join(ROOT, folder)), folder)
            self.assertTrue(os.path.isfile(os.path.join(ROOT, folder, "SKILL.md")), folder)
            self.assertTrue(os.path.isfile(os.path.join(ROOT, folder, SKILLS[folder])), folder)

    def test_front_matter_matches_the_folder(self):
        for folder in SKILLS:
            meta_path = os.path.join(ROOT, folder, "SKILL.md")
            meta, _ = front_matter(meta_path)
            self.assertTrue(meta, folder)
            name = re.search(r"^name:\s*(\S+)", meta, re.M)
            self.assertIsNotNone(name, folder)
            self.assertEqual(name.group(1), folder)
            desc = re.search(r"^description:\s*(.+)$", meta, re.M | re.S)
            self.assertIsNotNone(desc, folder)
            self.assertGreater(len(desc.group(1)), 80, folder)

    def test_skill_md_points_at_existing_scripts(self):
        for folder in SKILLS:
            _, body = front_matter(os.path.join(ROOT, folder, "SKILL.md"))
            for referenced in re.findall(r"\$\{CLAUDE_SKILL_DIR\}/([\w\-]+\.py)", body):
                self.assertTrue(os.path.isfile(os.path.join(ROOT, folder, referenced)),
                                "%s/%s" % (folder, referenced))

    def test_examples_are_valid_json(self):
        import json
        for name in ("mt5-core/config.example.json", "mt5-core/symbols.example.json",
                     "mt5-screener/rules.example.json", "mt5-alerts/alerts.example.json",
                     ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"):
            path = os.path.join(ROOT, name)
            self.assertTrue(os.path.isfile(path), name)
            with open(path, encoding="utf-8") as fh:
                json.load(fh)

    def test_scripts_compile_and_import_nothing_scary(self):
        tmp = tempfile.mkdtemp()
        for folder in SKILLS:
            path = os.path.join(ROOT, folder, SKILLS[folder])
            py_compile.compile(path, cfile=os.path.join(tmp, SKILLS[folder] + "c"),
                               doraise=True)
        for folder in SKILLS:
            path = os.path.join(ROOT, folder, SKILLS[folder])
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            self.assertNotIn("alpaca", source.lower(), folder)
            self.assertNotIn("13F", source, folder)
            self.assertNotIn("import pandas", source, folder)
            # MetaTrader5 may only be imported by the bridge
            if SKILLS[folder] != "bridge.py":
                self.assertNotIn("import MetaTrader5", source, folder)

    def test_third_party_imports_are_optional_or_stdlib(self):
        allowed = {"MetaTrader5", "numpy"}
        for folder in SKILLS:
            path = os.path.join(ROOT, folder, SKILLS[folder])
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line.startswith("import ") and not line.startswith("from "):
                        continue
                    module = line.split()[1].split(".")[0].rstrip(":")
                    if module in ("bridge_mod", "sizing", "core", "mt5"):
                        continue
                    self.assertTrue(module not in ("pandas", "requests", "yfinance"),
                                    "%s imports %s" % (folder, module))


if __name__ == "__main__":
    unittest.main()
