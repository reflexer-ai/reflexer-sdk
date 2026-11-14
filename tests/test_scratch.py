"""A run killed by a signal leaves no temp folder for good: the next run of its suite removes it (`scratch.py`), and
tools/ci.sh removes its own at the signal. Run: python -m unittest tests.test_scratch"""
import os, shutil, signal, subprocess, sys, time, unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "tests", "acceptance"))
import scratch  # noqa: E402

APPEARS_WITHIN = 120  # seconds a run is given to make its folder, at most: the suites' imports, on a loaded machine
POLL = 0.01  # seconds between two looks at the temp directory: a piece may make and remove its folder within a second
# Each piece that makes a folder: the command, and its folder's prefix. Each starts from the repo's root.
PIECES = {
    "bedrock": ([sys.executable, "-m", "unittest", "tests.test_bedrock"], "reflexer-bedrock-"),
    "litellm": ([sys.executable, "-m", "unittest", "tests.test_litellm"], "reflexer-litellm-"),
    "gates": ([sys.executable, "-m", "unittest", "tests.test_gates.Broken"], "reflexer-gates-"),
    "acceptance": ([sys.executable, "tests/acceptance/run.py", "--only", "breaker_opens_on_a_failure", "--condition", "a_freeze", "--tries", "1"],
                   "acceptance-"),  # a case frozen, so the run is still there when its folder is seen
    "docs": ([sys.executable, "-m", "unittest", "tests.acceptance.test_docs"], "docs-"),
    "controls": ([sys.executable, "-m", "unittest", "tests.acceptance.test_controls.Controls.test_the_sdk_as_it_is_is_green_where_the_faults_are_red"],
                 "acceptance-clean-"),
}


def dead_pid():
    """A process id whose process is gone: a child's, waited on."""
    child = subprocess.Popen([sys.executable, "-c", ""])
    child.wait()
    return child.pid


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = scratch.folder("scratch-test-")
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_removes_only_its_prefixs_folders_whose_process_is_gone(self):
        outside = os.path.join(self.tmp, "outside")
        os.mkdir(outside)
        gone = dead_pid()
        names = {"dead": f"made-up-{gone}-a", "alive": f"made-up-{os.getpid()}-b", "no_pid": "made-up-c",
                 "other_prefix": f"other-{gone}-d", "longer_prefix": f"made-up-more-{gone}-e"}
        root = os.path.join(self.tmp, "root")
        os.mkdir(root)
        for name in names.values():
            os.mkdir(os.path.join(root, name))
        os.symlink(outside, os.path.join(root, f"made-up-{gone}-link"))
        made = subprocess.run([sys.executable, "-c", "import scratch; print(scratch.folder('made-up-'))"], check=True, capture_output=True, text=True,
                              cwd=os.path.dirname(scratch.__file__), env=dict(os.environ, TMPDIR=root)).stdout.strip()
        self.assertEqual(os.path.dirname(made), root)
        left = set(os.listdir(root))
        self.assertNotIn(names["dead"], left)
        self.assertIn(os.path.basename(made), left)
        self.assertEqual({names[key] for key in ("alive", "no_pid", "other_prefix", "longer_prefix")} - left, set())
        self.assertTrue(os.path.isdir(outside), "a link's target is never removed")


class Killed(unittest.TestCase):
    """Each piece, started in a temp directory of its own and sent SIGTERM once its folder is there."""

    def setUp(self):
        self.tmp = scratch.folder("scratch-killed-")
        self.addCleanup(shutil.rmtree, self.tmp)

    def start(self, pieces):
        """Each piece started at once, in a temp directory and a process group of its own, and sent SIGTERM as soon as its
        new folder is there: each one's folder and exit status."""
        started = {}
        for piece, (command, prefix) in pieces.items():
            tmp = os.path.join(self.tmp, piece)
            os.makedirs(tmp, exist_ok=True)
            seen = set(os.listdir(tmp))
            process = subprocess.Popen(command, cwd=ROOT, env=dict(os.environ, TMPDIR=tmp), start_new_session=True,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.addCleanup(self.stop, process)
            started[piece] = (process, tmp, prefix, seen)
        made, deadline = {}, time.monotonic() + APPEARS_WITHIN
        while len(made) < len(started) and time.monotonic() < deadline:
            for piece, (process, tmp, prefix, seen) in started.items():
                new = [name for name in os.listdir(tmp) if name.startswith(prefix) and name not in seen]
                if piece in made:
                    continue
                if new:
                    made[piece] = (new[0], self.stop(process))
                elif process.poll() is not None:
                    self.fail(f"{piece}: ended with status {process.returncode} before making its folder")
            time.sleep(POLL)
        self.assertEqual(sorted(set(started) - set(made)), [], f"no folder within {APPEARS_WITHIN} s")
        return made

    def stop(self, process):
        """SIGTERM to the piece's group, as a terminal or a CI runner sends it, then its exit status."""
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        return process.wait()

    def test_each_pieces_folder_left_at_a_signal_is_removed_by_its_next_run(self):
        first = self.start(PIECES)
        self.assertEqual({piece: status for piece, (_, status) in first.items() if status != -signal.SIGTERM}, {}, "ended by SIGTERM, as by default")
        self.start(PIECES)
        left = [piece for piece, (folder, _) in first.items() if os.path.exists(os.path.join(self.tmp, piece, folder))]
        self.assertEqual(left, [], "the folder of the run killed is still there after the next run started")

    def test_ci_sh_removes_its_folder_at_a_signal(self):
        stub = os.path.join(self.tmp, "bin")
        os.mkdir(stub)
        with open(os.path.join(stub, "uv"), "w") as uv:  # made up: a `uv` that waits, where ci.sh's first step runs
            uv.write("#!/bin/sh\nexec sleep 60\n")
        os.chmod(os.path.join(stub, "uv"), 0o755)
        work = os.path.join(self.tmp, "work")
        os.mkdir(work)
        process = subprocess.Popen(["sh", "tools/ci.sh", "check"], cwd=ROOT, start_new_session=True,
                                   env=dict(os.environ, TMPDIR=work, PATH=stub + os.pathsep + os.environ["PATH"]),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop, process)
        deadline = time.monotonic() + APPEARS_WITHIN
        while not os.listdir(work) and time.monotonic() < deadline:
            time.sleep(POLL)
        self.assertNotEqual(os.listdir(work), [], "ci.sh made no folder")
        self.assertNotEqual(self.stop(process), 0)
        self.assertEqual(os.listdir(work), [])


if __name__ == "__main__":
    unittest.main()
