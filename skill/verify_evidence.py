#!/usr/bin/env python3
"""Check archived evidence, hashes and recorded outcomes without device access."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

def require(condition, message):
    if not condition:
        raise ValueError(message)

def read_json(root, name):
    return json.loads((root / name).read_text(encoding="utf-8-sig"))

def verify(root):
    manifest = read_json(root, "manifest.json")
    require(manifest["schema_version"] == 1, "Unsupported manifest schema")
    expected = {"old-reproduction.json", "candidate-hardware.json", "local-test-results.json",
                "model-checkpoints.json", "ds-integration.json", "ds-reconnect.json",
                "quotes.json", "reuse-results.json", "current-results.json"}
    require(len(manifest["files"]) == len(expected) and
            {x["file"] for x in manifest["files"]} == expected, "Evidence manifest is incomplete")
    for item in manifest["files"]:
        path = (root / item["file"]).resolve()
        require(path.parent == root.resolve(), "Evidence path must stay inside evidence directory")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        require(actual == item["sha256"], "SHA-256 mismatch: " + item["file"])
    old = read_json(root, "old-reproduction.json")["runs"]
    require(len(old) == 1, "Expected one archived failure reproduction")
    require(old[0]["returncode"] == 1 and old[0]["after_shape"] == "SQU", "Archived failure changed")
    require(old[0]["long_sine"] == old[0]["short_sine"] == "SIN", "Single-command comparison changed")
    fixed = read_json(root, "candidate-hardware.json")
    runs = fixed["runs"]
    require(len(runs) == 3, "Expected three archived hardware cases")
    for row, amplitude, output in zip(runs, (2.0, 1.0, 2.0), (0, 1, 1)):
        require(row["returncode"] == 0 and row["after_shape"] == "SIN", "Hardware case did not pass")
        require(float(row["after_amplitude"]) == amplitude, "Amplitude readback changed")
        require(int(row["initial_output"]) == int(row["after_output"]) == output, "Output state changed")
    require(fixed["restored"] is True and fixed["before"] == fixed["after"], "Restoration record changed")
    local = read_json(root, "local-test-results.json")
    require(local["native_tests"] == 10 and local["native_result"] == "PASS", "Native historical result changed")
    require(local["control_error_tests"] == 5 and local["control_result"] == "PASS", "Control historical result changed")
    require(local["ui_result"] == "PASS" and all(x in local["ui_checks"] for x in
            ("immediate readback", "green highlights", "whole-round clocks", "stale recovery", "no page errors")),
            "UI historical checks incomplete")
    require(local["ds_readiness_tests"] == 10 and local["ds_readiness_result"] == "PASS",
            "October 30 readiness record changed")
    for name, expected in (("model-checkpoints.json", 38), ("ds-integration.json", 23)):
        record = read_json(root, name)
        require(len(record["checks"]) == expected and record["errors"] == [],
                "Historical checkpoints changed: " + name)
    reconnect = read_json(root, "ds-reconnect.json")
    require(reconnect["ok"] is True and len(reconnect["replies"]) == 3, "DS reconnect probe failed")
    require(all(x == "LABMATE_LINK_OK_20261030" for x in reconnect["replies"]), "DS reply changed")
    require(reconnect["before"] == reconnect["after"], "Probe altered persistent data")
    require(reconnect["instrument_control_executed"] is False, "Probe control scope changed")
    quotes = read_json(root, "quotes.json")["quotes"]
    require(len(quotes) == 25 and len({x["id"] for x in quotes}) == 25, "Quote count or IDs changed")
    for row in quotes:
        require(row["thread_id"] and row["turn_id"] and row["quote"], "Quote source incomplete")
    for name in ("reuse-results.json", "current-results.json"):
        reused = read_json(root, name)
        require(reused["schema_version"] == 1 and reused["status"] == "PASS" and
                reused["executed_cases"] == 27, "Offline reuse result changed: " + name)
        expected_groups = {"refresh":5, "receipts":7, "relay-reconnect":4, "relay-readiness":11}
        require(len(reused["results"]) == 4 and
                {x["name"]:x["executed_cases"] for x in reused["results"]} == expected_groups,
                "Offline reuse groups incomplete: " + name)
        require(all(x["status"] == "PASS" and x["returncode"] == 0 and
                    x["expected_cases"] == x["executed_cases"] for x in reused["results"]),
                "Offline group failed: " + name)
    current = read_json(root, "current-results.json")
    require(current["engineering_package"]["version"] == "v20261101_09" and
            re.fullmatch(r"[0-9a-f]{64}", current["engineering_package"]["sha256"]),
            "Engineering package reference incomplete")
    require(current["source_sha256"] and all(re.fullmatch(r"[0-9a-f]{64}", value)
            for value in current["source_sha256"].values()), "Source hashes incomplete")
    print("PASS: %d evidence files match SHA-256." % len(manifest["files"]))
    print("PASS: archived SCPI failure + 3 corrected cases; state restoration recorded.")
    print("PASS: historical model checkpoints 38; DS integration 23; reconnect replies 3.")
    print("PASS: 25 sourced excerpts; November 1 and November 2 records each contain 27 cases (5 + 7 + 4 + 11).")
    print("Historical outcomes are verified as records; no hardware or cloud operation was performed.")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, default=Path(__file__).resolve().parent / "evidence")
    args = parser.parse_args()
    try:
        verify(args.evidence_dir)
        return 0
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print("FAIL:", exc, file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())

