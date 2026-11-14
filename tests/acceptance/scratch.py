"""The suites' temp folders, each named `reflexer-sdk-test-<name>-<pid>-<random>`: <pid> is the process that made it.

A folder goes on each way a run ends:
- a normal end or a failure: the code that asked for the folder removes it (a `finally`, `tearDown`, `addCleanup`);
- SIGTERM, SIGHUP or SIGINT: a handler, set once with the first folder, removes the folders this process made, then
  lets the signal end the run as it would have (its status stays the signal's); a forked child removes none of them;
- SIGKILL, which no handler sees: the next run that asks for a folder of the same name removes the folders whose
  process is gone (commons testing/GUIDE.md, Resources).
The sweep removes only names of exactly this form, real folders of this user, whose process is gone.

Command line, for tools/ci.sh: `python3 scratch.py NAME PID` prints a new folder named with PID; no handler is set."""
import os, re, shutil, signal, stat, sys, tempfile, threading

NAMESPACE = "reflexer-sdk-test-"
RANDOM = "[a-z0-9_]{8}"  # what tempfile adds to a name
SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
MADE = {}  # folder: the pid of the process that made it
BEFORE = {}  # signal: its handler before this module's


def pid_max():
    try:
        with open("/proc/sys/kernel/pid_max") as file:
            return int(file.read())
    except (OSError, ValueError):
        return 2 ** 22  # Linux's largest; other systems' are smaller


def gone(pid):
    """True only when no process has this id; False for a live one, or an id that is not one."""
    if pid > pid_max():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OverflowError, ValueError):
        return False
    return False


def sweep(root, prefix):
    for name in os.listdir(root):
        found = re.fullmatch(re.escape(prefix) + r"([1-9][0-9]{0,9})-" + RANDOM, name)
        if not found:
            continue
        path = os.path.join(root, name)
        try:
            held = os.lstat(path)
        except OSError:
            continue
        if stat.S_ISDIR(held.st_mode) and held.st_uid == os.getuid() and gone(int(found[1])):
            shutil.rmtree(path, ignore_errors=True)


def on_signal(number, frame):
    for path, pid in list(MADE.items()):
        if pid == os.getpid():
            shutil.rmtree(path, ignore_errors=True)
    before = BEFORE[number]
    if callable(before):  # SIGINT's KeyboardInterrupt, raised as before
        return before(number, frame)
    signal.signal(number, signal.SIG_DFL)
    os.kill(os.getpid(), number)


def hook():
    if BEFORE or threading.current_thread() is not threading.main_thread():
        return
    for number in SIGNALS:
        before = signal.getsignal(number)
        if before is signal.SIG_DFL or before is signal.default_int_handler:  # an ignored or a custom one is left alone
            BEFORE[number] = before
            signal.signal(number, on_signal)


def folder(name, pid=None):
    """A new folder `reflexer-sdk-test-<name>-<pid>-<random>` in the temp directory, after the sweep of that name. The
    code that asks for it removes it at a normal end or a failure; a signal's handler is set unless `pid` is given."""
    root, prefix = tempfile.gettempdir(), f"{NAMESPACE}{name}-"
    sweep(root, prefix)
    if pid is None:
        hook()  # before the folder is made: a signal on the way finds the handler set
    path = tempfile.mkdtemp(prefix=f"{prefix}{pid or os.getpid()}-", dir=root)
    if pid is None:
        MADE[path] = os.getpid()
    return path


if __name__ == "__main__":
    for number in SIGNALS:  # the folder is always printed, so the shell that asked has its name to remove
        signal.signal(number, signal.SIG_IGN)
    name, pid = sys.argv[1:]
    print(folder(name, int(pid)))
