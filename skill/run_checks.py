#!/usr/bin/env python3
"""Run existing LabMate tests in a disposable copy; no application services start."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

GUARD = r"""
import os, re, runpy, socket, subprocess, sys, tempfile, unittest
from pathlib import Path
def denied(*args, **kwargs):
    raise RuntimeError("Offline check blocked network or child process access")
socket.create_connection = denied
socket.socket.connect = denied
socket.socket.connect_ex = denied
subprocess.Popen = denied
def audit(event, args):
    if event in ("socket.connect", "subprocess.Popen", "os.system"):
        denied()
    if event == "open" and args and isinstance(args[0], (str, bytes)):
        value = os.fsdecode(args[0])
        if re.search(r"(?i)(?:^|[\\/])COM[0-9]+(?:$|:)", value) or value.startswith("/dev/"):
            raise RuntimeError("Offline check blocked device access")
sys.addaudithook(audit)
target = sys.argv[1]
tempfile.tempdir = str(Path(target).resolve().parents[1] / "test-data")
sys.argv = [target]
unittest.main = lambda *args, **kwargs: None
namespace = runpy.run_path(target, run_name="__skill_check__")
suite = unittest.TestSuite()
for value in namespace.values():
    if isinstance(value, type) and issubclass(value, unittest.TestCase):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(value))
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
"""

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--only", choices=("all", "refresh", "receipts", "relay"), default="all")
    parser.add_argument("--output", type=Path, help="Write a new result JSON; archived results remain unchanged by default")
    parser.add_argument("--work-dir", type=Path, help="Writable parent for the disposable copy; default: system temporary directory")
    args = parser.parse_args()
    root = args.project_root.resolve()
    if not root.is_dir():
        parser.error("Project root does not exist")
    sources = {}
    results = []
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    if args.work_dir:
        args.work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="labmate-skill-", dir=args.work_dir) as task_tmp:
        scratch = Path(task_tmp)
        (scratch / "test-data").mkdir()
        def copy_file(relative, destination=None):
            source = root / relative
            if not source.is_file():
                raise FileNotFoundError("Required engineering file missing: " + relative)
            sources[relative] = sha(source)
            dest = scratch / (destination or relative)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            return dest
        if args.only in ("all", "refresh", "receipts"):
            dashboard = root / "src/boot/labmate-control-v2/dashboard"
            if not dashboard.is_dir():
                raise FileNotFoundError("Engineering dashboard is missing")
            for source in sorted(dashboard.glob("*.py")):
                copy_file(source.relative_to(root).as_posix(), "dashboard/" + source.name)
        def run(name, command, expected, pattern, label):
            env = os.environ.copy()
            env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
            try:
                proc = subprocess.run(command, cwd=scratch, env=env, text=True,
                                      encoding="utf-8", errors="replace",
                                      capture_output=True, timeout=60)
                output = proc.stdout + proc.stderr
                match = re.search(pattern, output)
                count = int(match.group(1)) if match else 0
                ok = proc.returncode == 0 and count == expected
                results.append(dict(name=name, command=label, returncode=proc.returncode,
                                    expected_cases=expected, executed_cases=count,
                                    status="PASS" if ok else "FAIL", output=output.strip()))
            except subprocess.TimeoutExpired:
                results.append(dict(name=name, command=label, status="FAIL",
                                    expected_cases=expected, executed_cases=0, error="60 second timeout"))
        historical = "sim/historical/file_b19f499ecdf0/"
        for group, filename, count in (
            ("refresh", "test_refresh_legacy.py", 5),
            ("receipts", "test_experiment_summary.py", 7),
        ):
            if args.only not in ("all", group):
                continue
            target = copy_file(historical + filename, "tests/" + filename)
            run(group, [sys.executable, "-B", "-c", GUARD, str(target)],
                count, r"Ran (\d+) tests?", "python -B <offline-guard> tests/" + filename)
        if args.only in ("all", "relay"):
            target = copy_file("sim/test_relay_runner.py")
            copy_file("src/pc-background-launcher/run_cloud.py")
            run("relay-reconnect", [sys.executable, "-B", "-c", GUARD, str(target)],
                4, r"Ran (\d+) tests?", "python -B <offline-guard> sim/test_relay_runner.py")
            ps = shutil.which("powershell.exe") or shutil.which("pwsh")
            if ps is None:
                results.append(dict(name="relay-readiness", status="FAIL", expected_cases=11,
                                    executed_cases=0, error="Windows PowerShell or pwsh is required"))
            else:
                script = copy_file("sim/test_relay_startup.ps1")
                copy_file("src/pc-background-launcher/start-background.ps1")
                copy_file("src/pc-relay/start-cloud.ps1")
                run("relay-readiness", [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                       "-File", str(script)], 11, r"PASS: (\d+) relay readiness",
                    "powershell -NoProfile -NonInteractive -File sim/test_relay_startup.ps1")
    report = dict(schema_version=1, started_at=started,
                  finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                  environment=dict(python=platform.python_version(), system=platform.system(),
                                   system_release=platform.release()),
                  scope="Existing engineering tests in disposable copy; simulated I/O; no hardware or cloud requests",
                  status="PASS" if results and all(x["status"] == "PASS" for x in results) else "FAIL",
                  executed_cases=sum(x["executed_cases"] for x in results),
                  source_sha256=sources, results=results)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for row in results:
        print("%s: %s (%d/%d)" % (row["name"], row["status"], row["executed_cases"], row["expected_cases"]))
        if row["status"] != "PASS":
            print(row.get("error", row.get("output", "")))
    return 0 if report["status"] == "PASS" else 1

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print("FAIL:", exc, file=sys.stderr)
        raise SystemExit(1)

