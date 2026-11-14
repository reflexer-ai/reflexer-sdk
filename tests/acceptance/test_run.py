"""The suite's runner: a case's result reaches the table whole, or not at all. Offline. Run: python -m unittest tests.acceptance.test_run"""
import json, os, shutil, sys, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run, scratch  # noqa: E402


class Results(unittest.TestCase):
    def test_a_result_cut_while_written_leaves_no_file(self):
        """A case killed at its limit while it writes, or a result that cannot be written: the runner then reports the
        case killed or dead, not a crash of its own on a file half written."""
        def cut(result, file):
            file.write("{")
            raise KeyboardInterrupt("made up: the write is cut")
        tmp = scratch.folder("run")
        self.addCleanup(shutil.rmtree, tmp)
        with mock.patch.object(run.json, "dump", cut):
            out = os.path.join(tmp, "0.json")
            with self.assertRaises(KeyboardInterrupt):
                run.write_result({"status": "pass"}, out)
            self.assertFalse(os.path.exists(out))

    def test_a_result_written_reads_back(self):
        tmp = scratch.folder("run")
        self.addCleanup(shutil.rmtree, tmp)
        out = os.path.join(tmp, "0.json")
        run.write_result({"status": "pass"}, out)
        with open(out) as file:
            self.assertEqual(json.load(file), {"status": "pass"})
