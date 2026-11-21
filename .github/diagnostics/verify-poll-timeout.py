"""Check the submitted timeout test and its compatibility with current upstream."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

PATCH_HEAD = "73634a97af2f3b5d456c8da2afad701beec92575"
UPSTREAM = "749748e6b35eb63efeb24bac7ffd48331c818d62"


def git(directory, *args):
    return subprocess.check_output(["git", *args], cwd=directory)


def suite(directory, name, args):
    args = ["go", "test", "-json", "-count=1", *args]
    result = subprocess.run(args, cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    tests = {(v.get("Package"), v["Test"]) for v in events if v["Action"] == "pass" and v.get("Test")}
    packages = [v["Package"] for v in events if v["Action"] == "pass" and not v.get("Test")]
    failures = [v for v in events if v["Action"] in ("fail", "build-fail")]
    diagnostic = [v.get("Output", "").strip() for v in events if v["Action"] in ("build-output", "output")
                  and any(term in v.get("Output", "").lower() for term in ("assertion failed", "invalid array length", "build failed"))]
    passed = sorted(t for _, t in tests if t in {"TestWaitOn_WithCompare", "TestEqualMissingRoot"})
    receipt = {"exit":result.returncode, "tests_passed":len(tests), "packages_passed":packages,
               "named_cases":passed, "skips":[v["Test"] for v in events if v["Action"]=="skip" and v.get("Test")],
               "failures":failures, "diagnostics":diagnostic, "stderr":result.stderr.decode(errors="replace")[-1800:]}
    print(name, json.dumps(receipt),flush=True)
    return receipt


def main():
    original=Path("submitted")
    current=Path("current")
    assert git(original, "rev-parse", "HEAD").decode().strip()==PATCH_HEAD
    assert git(current, "rev-parse", "HEAD").decode().strip()==UPSTREAM
    delta=git(original,"diff","--binary","HEAD^","HEAD")
    assert git(original,"diff","--name-only","HEAD^","HEAD").decode().splitlines()==["poll/poll_test.go"]
    version = subprocess.check_output(["go","version"],text=True).strip()
    assert version=="go version go1.27.1 windows/amd64", version
    print(version,flush=True)
    results={}
    results["submitted poll"]=suite(original,"submitted poll",["./poll"])
    results["submitted Windows missing root"]=suite(original,"submitted missing root",["-run","^TestEqualMissingRoot$","./fs"])
    results["submitted migration tool"]=suite(original,"submitted migration tool",["-run","^$","./assert/cmd/gty-migrate-from-testify"])
    subprocess.run(["git","apply","--check","-"],cwd=current,input=delta,check=True)
    subprocess.run(["git","apply","-"],cwd=current,input=delta,check=True)
    assert git(current,"diff","--binary")==delta
    for mode,flags in (("normal",[]),("race",["-race"])):
        results["current root "+mode]=suite(current,"current root "+mode,[*flags,"./..."])
        results["current generics "+mode]=suite(current/"x/generics","current generics "+mode,[*flags,"./..."])
    record={"patch_head":PATCH_HEAD,"upstream":UPSTREAM,"patch_sha256":hashlib.sha256(delta).hexdigest(),"version":version,"results":results}
    Path("verification.json").write_text(json.dumps(record,indent=2)+"\n")
    assert results["submitted poll"]["exit"]==0 and "TestWaitOn_WithCompare" in results["submitted poll"]["named_cases"]
    for key,row in results.items():
        if key.startswith("current"):
            assert row["exit"]==0 and row["tests_passed"]>0 and not row["failures"], key
            if "root" in key:
                assert set(row["named_cases"])=={"TestEqualMissingRoot","TestWaitOn_WithCompare"} and "gotest.tools/v3/assert/cmd/gty-migrate-from-testify" in row["packages_passed"]


if __name__=="__main__":
    main()
