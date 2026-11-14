"""A run ended by a signal leaves no temp folder: at SIGTERM, SIGHUP or SIGINT the run removes it; at SIGKILL the next run
does (`tests/acceptance/scratch.py`, and tools/ci.sh). Run: python -m unittest tests.test_scratch"""
import os, shutil, signal, subprocess, sys, threading, time, unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HERE = os.path.join(ROOT, "tests", "acceptance")
sys.path.insert(0, HERE)
import scratch  # noqa: E402

APPEARS_WITHIN = 120  # seconds a run is given to make its folder, at most: the suites' imports, on a loaded machine
CASE_KILLED_WITHIN = 10  # seconds a case killed is given to be reaped, at most
POLL = 0.01  # seconds between two looks at the temp directory: a piece may make and remove its folder within a second
CI = ["sh", "tools/ci.sh", "check"]
# Each piece that makes a folder: the command, from the repo's root, its folder's name, and how many of its processes must
# run before the signal is sent, if more than one.
PIECES = {
    "bedrock": ([sys.executable, "-m", "unittest", "tests.test_bedrock"], "bedrock"),
    "litellm": ([sys.executable, "-m", "unittest", "tests.test_litellm"], "litellm"),
    "gates": ([sys.executable, "-m", "unittest", "tests.test_gates.Broken"], "gates"),
    "acceptance": ([sys.executable, "tests/acceptance/run.py", "--only", "breaker", "--jobs", "1", "--condition", "a_freeze", "--tries", "1"],
                   "acceptance", 2),  # cases frozen, one at a time, so the run is still there; the signal once a case runs
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


def running_in(tmp):
    """The processes still running with `tmp` as their temp directory: a piece's, and any it started."""
    found = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/environ", "rb") as file:
                if f"TMPDIR={tmp}".encode() in file.read().split(b"\0"):
                    found.append(int(pid))
        except OSError:
            pass
    return found


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
            command, name, *inside = PIECES[piece]
            tmp = os.path.join(self.tmp, piece)
            os.makedirs(tmp, exist_ok=True)
            started[piece] = (self.spawn(command, tmp), tmp, f"{scratch.NAMESPACE}{name}-", set(os.listdir(tmp)), inside)
        made, deadline = {}, time.monotonic() + APPEARS_WITHIN
        while len(made) < len(started) and time.monotonic() < deadline:
            for piece, (process, tmp, prefix, seen, inside) in started.items():
                new = [name for name in os.listdir(tmp) if name.startswith(prefix) and name not in seen]
                if piece in made:
                    continue
                if new and inside and len(running_in(tmp)) < inside[0]:
                    new = []
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
        self.assertEqual({piece: status for piece, (_, status) in made.items() if status != -signal.SIGTERM}, {}, "ended by SIGTERM, as by default")
        self.assertEqual({piece: running_in(os.path.join(self.tmp, piece)) for piece in made if running_in(os.path.join(self.tmp, piece))}, {},
                         "a process of the run still running: acceptance's cases are each in a process group of their own")

    def test_sighup_and_sigint_remove_the_folder_and_end_the_run_as_by_default(self):
        for number in (signal.SIGHUP, signal.SIGINT):
            with self.subTest(number.name):
                process, folder = self.held(self.tmp)
                self.assertTrue(os.path.isdir(folder))
                status = self.signal(process, number)
                self.assertFalse(os.path.exists(folder))
                self.assertIn(status, (-number, 1))  # SIGINT: Python's KeyboardInterrupt, which ends with -SIGINT or 1

    def test_the_acceptance_run_at_a_signal_kills_its_cases_before_its_folder_goes(self):
        import run
        case = subprocess.Popen(["sleep", "60"], start_new_session=True)  # made up: a case, in a process group of its own
        self.addCleanup(lambda: case.poll() is None and (case.kill(), case.wait()))
        run.RUNNING[case.pid] = None
        self.addCleanup(run.RUNNING.pop, case.pid, None)
        alive = []
        run.killing_the_cases(lambda number, frame: alive.append(os.path.exists(f"/proc/{case.pid}")), os.getpid() + 1)(signal.SIGTERM, None)
        self.assertEqual(alive, [True], "a case's own process kills no other case")
        handled = threading.Thread(target=run.killing_the_cases(lambda number, frame: alive.append(os.path.exists(f"/proc/{case.pid}")), os.getpid()),
                                   args=(signal.SIGTERM, None))
        handled.start()
        handled.join(CASE_KILLED_WITHIN)
        self.assertEqual(alive, [True, False], "the case is killed and reaped before the folder's handler runs")

    def test_a_forked_child_ended_by_a_signal_leaves_its_parents_folder(self):
        process = self.spawn([sys.executable, "-c", FORKED], self.tmp, HERE)
        path, kept = process.stdout.readline().split()
        self.assertEqual(kept, "True")
        self.signal(process, signal.SIGTERM)
        self.assertFalse(os.path.exists(path))

    def test_a_folder_left_at_sigkill_is_removed_by_the_next_run(self):
        first = self.start(["ci"], signal.SIGKILL)["ci"][0]
        self.assertTrue(os.path.isdir(first), "SIGKILL leaves the folder: no handler sees it")
        self.start(["ci"], signal.SIGKILL)
        self.assertFalse(os.path.exists(first), "ci: the folder of the run killed is still there after the next run started")
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
        kept = [f"{prefix}{os.getpid()}-abcd_123", f"{prefix}1-abcd_123",  # alive; alive, of another user (init)
                f"{prefix}2026-11-14", "made-up-2026-notes",  # a date, a name that only looks like one
                f"{prefix}{gone}-abc", f"{prefix}{gone}-abcd_1234", f"{prefix}{gone}-ABCD_123",  # not tempfile's random part
                f"{prefix}9999999999-abcd_123",  # too large for os.kill
                f"{prefix}99999999999999999999-abcd_123"]  # longer than any pid
        removed_too = [f"{scratch.NAMESPACE}other-{gone}-abcd_123", f"{prefix}more-{gone}-abcd_123",  # other names of the namespace
                       f"{scratch.NAMESPACE}ts-gates-{gone}-AbCd12"]  # Node's
        for name in [removed, *removed_too, *kept]:
            os.mkdir(os.path.join(root, name))
        with open(os.path.join(root, f"{prefix}{gone}-file_123"), "w"):  # a file, not a folder
            pass
        os.symlink(outside, os.path.join(root, f"{prefix}{gone}-link_123"))
        process, made = self.held(root)
        left = set(os.listdir(root))
        self.assertEqual(sorted({removed, *removed_too} & left), [])
        self.assertEqual(sorted(set(kept) - left), [])
        self.assertEqual({f"{prefix}{gone}-file_123", f"{prefix}{gone}-link_123", os.path.basename(made)} - left, set())
        self.assertTrue(os.path.isdir(outside), "a link's target is never removed")


if __name__ == "__main__":
    unittest.main()
