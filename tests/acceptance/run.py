#!/usr/bin/env python3
"""Runs the acceptance suite on the SDK, offline: `python tests/acceptance/run.py [--only TEXT] [--sdk SDK] [--json PATH]`.

Each case runs on each SDK in a forked process of its own, with its own stand-ins, and is killed at its limit. Prints a
table and a line per cell not passed; exits 1 when a cell fails. `--fault NAME` plants a fault of `faults.py` in every
case, and `--condition NAME` a slow machine's moment of its `CONDITIONS`, for `test_controls.py`.

pass: held. fail: broken. cannot: the case cannot apply; it stays in the table with what the client sees. open: a known
gap, failing on what is not built yet; reported, not failing the run. `-`: that SDK has no such call.
"""
import argparse, importlib.metadata, json, logging, os, shutil, signal, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [HERE, ROOT]  # the suite's modules, and the SDK of this checkout
from harness import bedrock, litellm  # noqa: E402 Bedrock's libraries and its wire, LiteLLM's providers, as the suite plays them

SDK_COLUMNS = ("openai", "anthropic", "gemini", "azure", "acme", *bedrock.COLUMNS, *litellm.COLUMNS)
VERSIONS = ("openai", "anthropic", "google-genai", "httpx2", "httpx", "boto3", "aiobotocore", "litellm", "langchain-aws", "strands-agents",
            "pydantic-ai-slim")
AMBIENT = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
           "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID", "OPENAI_CUSTOM_HEADERS",
           "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS",
           "GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_GEMINI_BASE_URL", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT",
           "OPENAI_API_VERSION", "SSL_CERT_DIR", *bedrock.AMBIENT)  # nothing of the caller's environment reaches a case
GRACE_AFTER_ALARM = 2  # seconds between a case's own alarm and its kill
MAX_JOBS = 8


def jobs_for(cases, only, only_sdk, most_tries):
    """One job per case and SDK. Those that cannot apply carry their reason and do not run. A `steady` case's tries,
    at most `most_tries`."""
    jobs = []
    for case in cases:
        if only and not any(text in case["name"] for text in only):
            continue
        for sdk in (*case["sdks"], *[s for s in case["na"] if s not in case["sdks"]]):
            if not only_sdk or sdk == only_sdk:
                jobs.append({"case": case, "sdk": sdk, "cannot": case["na"].get(sdk), "tries": min(case["tries"], most_tries or case["tries"])})
    return jobs


class HardLimit(BaseException):
    """Past what any SDK catches as an error of its own."""


def run_in_child(job, fault, condition, contexts, out_path, log_path, limit):
    """The forked process: one case, one world. It never returns."""
    import faults, harness, lines
    os.setsid()
    log = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    os.dup2(log, 1)
    os.dup2(log, 2)
    case, sdk = job["case"], job["sdk"]
    result = {"case": case["name"], "behaviour": case["behaviour"], "sdk": sdk, "status": "fail", "saw": "", "data": {}}
    began = time.monotonic()

    def hung(*_):
        raise HardLimit(f"hung: its limit of {limit:.0f}s")

    signal.signal(signal.SIGALRM, hung)
    test = None
    try:
        harness.seed_for(f"{case['name']}/{sdk}")
        if fault:
            faults.FAULTS[fault]()
        if condition:
            faults.CONDITIONS[condition](case["name"])
        stalls = []
        for _ in range(job["tries"]):  # a try the machine stalled is not judged, when the case is `steady`
            signal.setitimer(signal.ITIMER_REAL, max(limit - GRACE_AFTER_ALARM, 1))  # each try's limit
            ticker, failure = harness.Ticker(), None
            test = harness.Test(lines, sdk, harness.World(contexts))
            try:
                case["run"](test)
                test.invariants()
            except harness.Fail as failed:
                failure = failed
            finally:
                logging.getLogger().removeHandler(test.logs)  # a thread left of this try logs into no other's
            stalled = ticker.stop()
            if stalled <= harness.STALL or job["tries"] == 1:
                break
            stalls.append(f"{stalled:.2f}s, {'red' if failure else 'green'}")
        else:
            failure = harness.Fail(f"the machine stalled each of {job['tries']} tries: none judged")
        if stalls:
            test.note(f"tried again after the machine stalled: {'; '.join(stalls)}")
            test.data["stalls"] = stalls
        if failure is not None:
            raise failure
        result["status"], result["saw"] = "pass", test.saw()
    except harness.Cannot as reason:
        result["status"], result["saw"] = "cannot", str(reason)
    except BaseException as failure:
        kind = "" if isinstance(failure, harness.Fail) else f"{type(failure).__name__}: "
        result["saw"] = f"{kind}{failure}".replace(harness.make_key(), "<the key>")[:400]
        if test is not None:
            result["saw"] += f" [{test.saw()}]"
        traceback.print_exc()
    signal.setitimer(signal.ITIMER_REAL, 0)
    if test is not None:
        result["data"] = test.data
    result["seconds"] = round(time.monotonic() - began, 2)
    write_result(result, out_path)
    sys.stdout.flush()
    os._exit(0)


def write_result(result, out_path):
    """The case's result at `out_path`, whole, or no file at all: written aside, then moved in one step. A case killed at
    its limit while it writes is reported killed, never as a file the runner cannot read."""
    with open(out_path + ".part", "w") as out:
        json.dump(result, out)
    os.replace(out_path + ".part", out_path)


def run_jobs(jobs, fault, condition, contexts, tmp, parallel):
    """Forks up to `parallel` at a time. A case past its limit is killed with what it started; none stops the run."""
    results, waiting, running = [], list(enumerate(jobs)), {}
    while waiting or running:
        while waiting and len(running) < parallel:
            index, job = waiting.pop(0)
            common = {"case": job["case"]["name"], "behaviour": job["case"]["behaviour"], "sdk": job["sdk"], "data": {}, "seconds": 0.0}
            if job["cannot"]:
                results.append((index, job, common | {"status": "cannot", "saw": job["cannot"]}))
                continue
            out, log = os.path.join(tmp, f"{index}.json"), os.path.join(tmp, f"{index}.log")
            limit = job["case"]["limit"]
            sys.stdout.flush()
            pid = os.fork()
            if pid == 0:
                try:
                    run_in_child(job, fault, condition, contexts, out, log, limit)
                finally:
                    os._exit(1)
            running[pid] = (index, job, out, limit, time.monotonic() + limit * job["tries"], common)
        for pid, (index, job, out, limit, deadline, common) in list(running.items()):
            done, status = os.waitpid(pid, os.WNOHANG)
            if done == 0 and time.monotonic() < deadline:
                continue
            if done == 0:
                os.killpg(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            try:
                os.killpg(pid, signal.SIGKILL)  # what the case started and left behind
            except (ProcessLookupError, PermissionError):
                pass
            del running[pid]
            if os.path.exists(out):
                with open(out) as result:
                    results.append((index, job, json.load(result)))
            else:
                why = "killed at its hard limit" if done == 0 else f"its process died, status {status}"
                results.append((index, job, common | {"status": "fail", "saw": why, "seconds": limit * job["tries"] if done == 0 else 0.0}))
        time.sleep(0.005)
    return sorted(results, key=lambda row: row[0])


def build(rows):
    """The table's rows: a failure on an SDK the case lists as open is `open`."""
    return [row | {"status": "open" if row["status"] == "fail" and row["sdk"] in job["case"]["open_on"] else row["status"]}
            for _, job, row in rows]


def summary(table):
    counts = {"pass": 0, "fail": 0, "cannot": 0, "open": 0}
    for row in table:
        counts[row["status"]] += 1
    return counts


def rendered(table, seconds, versions):
    """The table: a line per case with a word per SDK, then each cell not passed with what the client saw."""
    lines = [f"{seconds:.0f}s on {versions}.", ""]
    width = max(len(row["case"]) for row in table) + 2
    behaviours = list(dict.fromkeys(row["behaviour"] for row in table))
    for behaviour in behaviours:
        rows = [row for row in table if row["behaviour"] == behaviour]
        columns = [sdk for sdk in SDK_COLUMNS if any(row["sdk"] == sdk for row in rows)]  # those its cases run on
        lines += [f"== {behaviour}", f"{'case':<{width}}" + "".join(f"{sdk[:16]:<17}" for sdk in columns)]
        for name in dict.fromkeys(row["case"] for row in rows):
            cells = {row["sdk"]: row["status"] for row in rows if row["case"] == name}
            lines.append((f"{name:<{width}}" + "".join(f"{cells.get(sdk, '-'):<17}" for sdk in columns)).rstrip())
        lines.append("")
    lines.append("Sum: " + ", ".join(f"{word} {count}" for word, count in summary(table).items()) + f", of {len(table)} cells.")
    lines += ["", "Each not passed:"] + [f"{row['status']:<7} {row['case']} / {row['sdk']}: {row['saw']}"
                                         for row in table if row["status"] != "pass"]
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", action="append", help="only cases whose name holds this text; may repeat")
    parser.add_argument("--sdk", choices=SDK_COLUMNS)
    parser.add_argument("--jobs", type=int, default=min(MAX_JOBS, os.cpu_count() or 1))
    parser.add_argument("--fault", help="a fault of faults.py, planted in every case")
    parser.add_argument("--condition", help="a slow machine's moment, of faults.py's CONDITIONS, planted in every case")
    parser.add_argument("--tries", type=int, help="at most this many tries of a `steady` case; 1: its one try judged, stalled or not")
    parser.add_argument("--json", help="also write the table, with what each cell saw and measured, to this file")
    arguments = parser.parse_args()

    for name in AMBIENT:
        os.environ.pop(name, None)
    import faults, harness, lines, scratch  # noqa: F401 lines: the SDKs, imported once before the forks
    from harness import certs
    if arguments.fault and arguments.fault not in faults.FAULTS:
        parser.error(f"no such fault: {arguments.fault}")
    if arguments.condition and arguments.condition not in faults.CONDITIONS:
        parser.error(f"no such condition: {arguments.condition}")
    harness.resolver.install()
    tmp = scratch.folder("acceptance")
    try:
        authority = certs.Certs(tmp, harness.NAMES)
        os.environ["SSL_CERT_FILE"] = os.environ["AWS_CA_BUNDLE"] = authority.ca  # AWS_CA_BUNDLE: botocore's own trust
        os.environ.update(bedrock.ENVIRONMENT)
        import cases
        versions = ", ".join(f"{name} {importlib.metadata.version(name)}" for name in VERSIONS)
        began = time.monotonic()
        jobs = jobs_for(cases.CASES, arguments.only, arguments.sdk, arguments.tries)
        rows = run_jobs(jobs, arguments.fault, arguments.condition, (authority.context(), authority.untrusted()), tmp, arguments.jobs)
        seconds = time.monotonic() - began
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    table = build(rows)
    print("\n".join(rendered(table, seconds, versions)))
    if arguments.json:
        with open(arguments.json, "w") as out:
            json.dump({"fault": arguments.fault, "condition": arguments.condition, "seconds": round(seconds, 1), "versions": versions, "summary": summary(table),
                       "cases": table}, out, indent=1)
    return 1 if summary(table)["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
