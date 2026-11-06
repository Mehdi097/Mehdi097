"""The .exe entry point: command table, frozen paths, bootstrap, and running it."""

import os
import shutil
import sys
import tempfile
import unittest

import _load

runner = _load.load("mt5-app", "runner")
ROOT = _load.ROOT


class TestCommands(unittest.TestCase):
    def test_every_command_points_at_a_real_script(self):
        for name, (folder, module, _prefix, _what, _sends) in runner.COMMANDS.items():
            self.assertTrue(runner.skill_path(folder, module),
                            "%s -> %s/%s.py" % (name, folder, module))

    def test_menu_entries_are_commands(self):
        for _key, command, _label in runner.MENU:
            self.assertIn(command.split(" ")[0], runner.COMMANDS)

    def test_dangerous_commands_are_flagged(self):
        for name in ("send", "close", "close-all"):
            self.assertTrue(runner.COMMANDS[name][4], name)
        for name in ("check", "tickets", "journal", "analyze"):
            self.assertFalse(runner.COMMANDS[name][4], name)

    def test_resolve_injects_prefix_and_trader_dir(self):
        folder, module, argv, sends = runner.resolve("plan", ["--write"])
        self.assertEqual((folder, module), ("mt5-budget", "size"))
        self.assertFalse(sends)
        self.assertIn("--trader-dir", argv)
        self.assertIn("--write", argv)

    def test_resolve_keeps_an_explicit_trader_dir(self):
        _f, _m, argv, _s = runner.resolve("check", ["--trader-dir", "/tmp/x"])
        self.assertEqual(argv.count("--trader-dir"), 1)

    def test_unknown_command(self):
        self.assertEqual(_load.run(runner, ["nope"]), 2)


class TestFrozenPaths(unittest.TestCase):
    """A frozen exe has no source tree: sys._MEIPASS is the pack."""

    def setUp(self):
        self._had = hasattr(sys, "_MEIPASS")
        self._old = getattr(sys, "_MEIPASS", None)

    def tearDown(self):
        if self._had:
            sys._MEIPASS = self._old
        elif hasattr(sys, "_MEIPASS"):
            del sys._MEIPASS

    def test_pack_root_follows_meipass(self):
        sys._MEIPASS = ROOT
        self.assertEqual(os.path.abspath(runner.pack_root()), os.path.abspath(ROOT))

    def test_skill_path_from_a_lonely_copy(self):
        # copy only runner.py somewhere with no sibling folders, then pretend the
        # bundle lives at the pack root: resolution must still work
        tmp = tempfile.mkdtemp()
        try:
            lonely = os.path.join(tmp, "runner.py")
            shutil.copyfile(os.path.join(ROOT, "mt5-app", "runner.py"), lonely)
            sys._MEIPASS = ROOT
            for folder, module in (("mt5-core", "bridge"), ("mt5-broker", "execute"),
                                   ("mt5-budget", "size")):
                path = runner.skill_path(folder, module)
                self.assertIsNotNone(path, folder)
                self.assertTrue(path.startswith(os.path.abspath(ROOT)), path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_skill_says_where_it_looked(self):
        sys._MEIPASS = tempfile.mkdtemp()
        self.assertIsNone(runner.skill_path("mt5-nope", "nope"))


class TestBootstrap(unittest.TestCase):
    def test_creates_config_and_symbols(self):
        tmp = tempfile.mkdtemp()
        try:
            root = os.path.join(tmp, "trader")
            created = runner.bootstrap(root)
            self.assertTrue(any(p.endswith("config.json") for p in created))
            self.assertTrue(any(p.endswith("symbols.json") for p in created))
            self.assertTrue(os.path.isdir(os.path.join(root, "state")))
            self.assertTrue(os.path.isdir(os.path.join(root, "data")))
            cfg = _load.read_json(os.path.join(root, "config.json"))
            self.assertIn("allow_live", cfg)
            self.assertFalse(cfg["allow_live"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_never_overwrites(self):
        tmp = tempfile.mkdtemp()
        try:
            root = os.path.join(tmp, "trader")
            runner.bootstrap(root)
            path = os.path.join(root, "config.json")
            cfg = _load.read_json(path)
            cfg["allow_live"] = True
            _load.write_json(path, cfg)
            runner.bootstrap(root)
            self.assertTrue(_load.read_json(path)["allow_live"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestRunning(unittest.TestCase):
    def test_version_and_help(self):
        self.assertEqual(_load.run(runner, ["version"]), 0)
        self.assertEqual(_load.run(runner, ["help"]), 0)

    def test_spec_offline_through_the_runner(self):
        tmp = tempfile.mkdtemp()
        try:
            root = _load.make_trader(tmp)
            code = _load.run(runner, ["spec", "--offline", "EURUSD", "--trader-dir", root])
            self.assertEqual(code, 0)
        finally:
            _load.cleanup(tmp)

    def test_status_offline_through_the_runner(self):
        tmp = tempfile.mkdtemp()
        try:
            root = _load.make_trader(tmp)
            self.assertEqual(_load.run(runner, ["status", "--offline", "--trader-dir", root]), 0)
        finally:
            _load.cleanup(tmp)

    def test_sending_flag_is_announced(self):
        self.assertTrue(runner.COMMANDS["send"][4])


if __name__ == "__main__":
    unittest.main()
