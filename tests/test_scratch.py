"""A run ended by a signal leaves no temp folder: at SIGTERM, SIGHUP or SIGINT the run removes it; at SIGKILL the next run
does (`tests/acceptance/scratch.py`, and tools/ci.sh). Run: python -m unittest tests.test_scratch"""
import os, shutil, signal, subprocess, sys, time, unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HERE = os.path.join(ROOT, "tests", "acceptance")
sys.path.insert(0, HERE)
import scratch  # noqa: E402

APPEARS_WITHIN = 120  # seconds a run is given to make its folder, at most: the suites' imports, on a loaded machine
POLL = 0.01  # seconds between two looks at the temp directory: a piece may make and remove its folder within a second
CI = ["sh", "tools/ci.sh", "check"]
# Each piece that makes a folder: the command, from the repo's root, and its folder's name.
PIECES = {
    "bedrock": ([sys.executable, "-m", "unittest", "tests.test_bedrock"], "bedrock"),
    "litellm": ([sys.executable, "-m", "unittest", "tests.test_litellm"], "litellm"),
    "gates": ([sys.executable, "-m", "unittest", "tests.test_gates.Broken"], "gates"),
    "acceptance": ([sys.executable, "tests/acceptance/run.py", "--only", "breaker_opens_on_a_failure", "--condition", "a_freeze", "--tries", "1"],
                   "acceptance"),  # a case frozen, so the run is still there when its folder is seen
    "docs": ([sys.executable, "-m", "unittest", "tests.acceptance.test_docs"], "docs"),
    "controls": ([sys.executable, "-m", "unittest", "tests.acceptance.test_controls.Controls.test_the_sdk_as_it_is_is_green_where_the_faults_are_red"], "clean"),
    "ci": (CI, "ci"),
}
HOLD = "import os, scratch, sys, time; print(scratch.folder(sys.argv[1]), flush=True); time.sleep(60)"  # a folder, then a wait
FORKED = """import os, scratch, signal, time
path = scratch.folder("fork")
ready, said = os.pipe()
child = os.fork()
if child == 0:
    os.write(said, b"r")  # running: a signal sent before the child's Python has set itself up after the fork is lost
    time.sleep(60)
    os._exit(0)
os.read(ready, 1)
os.kill(child, signal.SIGTERM)
os.waitpid(child, 0)
print(path, os.path.isdir(path), flush=True)
time.sleep(60)
"""


def dead_pid():
    """A process id whose process is gone: a child's, waited on."""
    child = subprocess.Popen([sys.executable, "-c", ""])
    child.wait()
    return child.pid


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = scratch.folder("scratch")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.bin = os.path.join(self.tmp, "bin")
        os.mkdir(self.bin)
        with open(os.path.join(self.bin, "uv"), "w") as uv:  # made up: a `uv` that waits, where ci.sh's first step runs
            uv.write("#!/bin/sh\nexec sleep 60\n")
        os.chmod(os.path.join(self.bin, "uv"), 0o755)

    def spawn(self, command, tmp, cwd=ROOT):
        process = subprocess.Popen(command, cwd=cwd, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                   env=dict(os.environ, TMPDIR=tmp, PATH=self.bin + os.pathsep + os.environ["PATH"]))
        self.addCleanup(lambda: (self.signal(process, signal.SIGKILL), process.stdout.close()))
        return process

    @staticmethod
    def signal(process, number):
        """`number` to the process's group, as a terminal or a CI runner sends it, then its exit status."""
        try:
            os.killpg(process.pid, number)
        except ProcessLookupError:
            pass
        return process.wait()

    def held(self, tmp, name="made-up"):
        """A process holding a folder of `name` in `tmp`, and that folder."""
        process = self.spawn([sys.executable, "-c", HOLD, name], tmp, HERE)
        return process, process.stdout.readline().strip()

    def start(self, pieces, number):
        """Each piece started at once, in a temp directory and a process group of its own, and sent `number` as soon as its
        new folder is there: each one's folder and exit status."""
        started = {}
        for piece in pieces:
            command, name = PIECES[piece]
            tmp = os.path.join(self.tmp, piece)
            os.makedirs(tmp, exist_ok=True)
            started[piece] = (self.spawn(command, tmp), tmp, f"{scratch.NAMESPACE}{name}-", set(os.listdir(tmp)))
        made, deadline = {}, time.monotonic() + APPEARS_WITHIN
        while len(made) < len(started) and time.monotonic() < deadline:
            for piece, (process, tmp, prefix, seen) in started.items():
                new = [name for name in os.listdir(tmp) if name.startswith(prefix) and name not in seen]
                if piece in made:
                    continue
                if new:
                    made[piece] = (os.path.join(tmp, new[0]), self.signal(process, number))
                elif process.poll() is not None:
                    self.fail(f"{piece}: ended with status {process.returncode} before making its folder")
            time.sleep(POLL)
        self.assertEqual(sorted(set(started) - set(made)), [], f"no folder within {APPEARS_WITHIN} s")
        return made

    def test_each_piece_removes_its_folder_at_sigterm(self):
        made = self.start(PIECES, signal.SIGTERM)
        self.assertEqual([piece for piece, (folder, _) in made.items() if os.path.exists(folder)], [], "a folder left at SIGTERM")
        self.assertEqual({piece: status for piece, (_, status) in made.items() if status != (1 if piece == "ci" else -signal.SIGTERM)}, {},
                         "ended by SIGTERM, as by default; ci.sh: exit 1, by its trap")

    def test_sighup_and_sigint_remove_the_folder_and_end_the_run_as_by_default(self):
        for number in (signal.SIGHUP, signal.SIGINT):
            with self.subTest(number.name):
                process, folder = self.held(self.tmp)
                self.assertTrue(os.path.isdir(folder))
                status = self.signal(process, number)
                self.assertFalse(os.path.exists(folder))
                self.assertIn(status, (-number, 1))  # SIGINT: Python's KeyboardInterrupt, which ends with -SIGINT or 1

    def test_a_forked_child_ended_by_a_signal_leaves_its_parents_folder(self):
        process = self.spawn([sys.executable, "-c", FORKED], self.tmp, HERE)
        path, kept = process.stdout.readline().split()
        self.assertEqual(kept, "True")
        self.signal(process, signal.SIGTERM)
        self.assertFalse(os.path.exists(path))

    def test_a_folder_left_at_sigkill_is_removed_by_the_next_run(self):
        for piece in ("ci",):
            first = self.start([piece], signal.SIGKILL)
            self.assertTrue(os.path.isdir(first[piece][0]), "SIGKILL leaves the folder: no handler sees it")
            self.start([piece], signal.SIGKILL)
            self.assertFalse(os.path.exists(first[piece][0]), f"{piece}: the folder of the run killed is still there after the next run started")
        process, folder = self.held(self.tmp)
        self.signal(process, signal.SIGKILL)
        self.assertTrue(os.path.isdir(folder), "SIGKILL leaves the folder: no handler sees it")
        self.held(self.tmp)
        self.assertFalse(os.path.exists(folder))

    def test_the_sweep_removes_only_its_names_real_folders_of_this_user_whose_process_is_gone(self):
        root, outside, gone = os.path.join(self.tmp, "root"), os.path.join(self.tmp, "outside"), dead_pid()
        os.mkdir(root)
        os.mkdir(outside)
        prefix = f"{scratch.NAMESPACE}made-up-"
        removed = f"{prefix}{gone}-abcd_123"
        kept = [f"{prefix}{os.getpid()}-abcd_123",  # alive
                f"{prefix}2026-11-14", "made-up-2026-notes",  # a date, a name that only looks like one
                f"{prefix}{gone}-abc", f"{prefix}{gone}-abcd_1234", f"{prefix}{gone}-ABCD_123",  # not tempfile's random part
                f"{prefix}9999999999-abcd_123",  # above any pid_max
                f"{prefix}99999999999999999999-abcd_123",  # too large for os.kill
                f"{scratch.NAMESPACE}other-{gone}-abcd_123", f"{prefix}more-{gone}-abcd_123"]  # other names
        for name in [removed, *kept]:
            os.mkdir(os.path.join(root, name))
        with open(os.path.join(root, f"{prefix}{gone}-file_123"), "w"):  # a file, not a folder
            pass
        os.symlink(outside, os.path.join(root, f"{prefix}{gone}-link_123"))
        process, made = self.held(root)
        left = set(os.listdir(root))
        self.assertNotIn(removed, left)
        self.assertEqual(sorted(set(kept) - left), [])
        self.assertEqual({f"{prefix}{gone}-file_123", f"{prefix}{gone}-link_123", os.path.basename(made)} - left, set())
        self.assertTrue(os.path.isdir(outside), "a link's target is never removed")


if __name__ == "__main__":
    unittest.main()
