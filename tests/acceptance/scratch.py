"""The suites' temp folders: named with the process id of the run that made them, so the next run removes those whose
process is gone. A run killed by a signal (SIGTERM, SIGINT, SIGHUP, or SIGKILL, which no handler sees) runs no `finally`
or `tearDown`, and its folder stays until then (commons testing/GUIDE.md, Resources: a temporary named with the writer's
process id, removed in a `finally`; one whose process is gone removed by the next run). No signal is handled here, so a
forked child removes nothing of its parent's, and a signal ends a run as it always did."""
import os, re, shutil, tempfile


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # another user's process
        return True
    return True


def folder(prefix):
    """A new folder `<prefix><pid>-<random>` in the temp directory, its caller removing it. First removes the folders
    named so with `prefix` whose process is gone: only those, never another name."""
    root = tempfile.gettempdir()
    for name in os.listdir(root):
        found = re.fullmatch(re.escape(prefix) + r"([1-9][0-9]*)-[^/]+", name)
        if found and not alive(int(found[1])):
            shutil.rmtree(os.path.join(root, name), ignore_errors=True)  # a link is refused by rmtree, not followed
    return tempfile.mkdtemp(prefix=f"{prefix}{os.getpid()}-", dir=root)
