"""Independent widget-counter acceptance checks, kept outside agent fixtures."""

import json
import subprocess
import sys
from pathlib import Path


def evaluate(repo: Path) -> dict:
    checks = []
    for arguments, expected, structured in [
        ([], "0 widgets", False), (["3"], "3 widgets", False),
        (["--json"], {"widgets": 0}, True),
        (["3", "--json"], {"widgets": 3}, True),
        (["--json", "-2"], {"widgets": -2}, True),
    ]:
        result = subprocess.run([sys.executable, str(repo / "count.py"), *arguments],
                                capture_output=True, text=True)
        actual = result.stdout.strip()
        if structured:
            try:
                actual = json.loads(actual)
            except ValueError:
                actual = None
        passed = result.returncode == 0 and actual == expected and not result.stderr
        if structured and isinstance(actual, dict):
            passed = passed and type(actual.get("widgets")) is int
        checks.append({"arguments": arguments, "pass": passed, "exit_code": result.returncode,
                       "stdout": result.stdout, "stderr": result.stderr})
    result = subprocess.run([sys.executable, str(repo / "count.py"), "invalid"],
                            capture_output=True, text=True)
    checks.append({"arguments": ["invalid"], "pass": result.returncode != 0 and bool(result.stderr.strip()),
                   "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    return {"verdict": "pass" if all(check["pass"] for check in checks) else "fail", "checks": checks}


if __name__ == "__main__":
    result = evaluate(Path(sys.argv[1]).resolve())
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["verdict"] == "pass" else 1)
