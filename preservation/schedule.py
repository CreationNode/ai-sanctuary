"""Run periodic preservation checks for a custody inventory."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("audit", "golden"))
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--mirrors", type=Path)
    parser.add_argument("--alert-command", nargs="+", help="Program receiving alert JSON on stdin")
    args = parser.parse_args()
    inventory = archive.read_json(args.inventory)
    archive.require(isinstance(inventory, dict) and inventory, "Provide a custody inventory of admitted releases")
    failed = []
    for identifier, sha in inventory.items():
        archive.model_id(identifier)
        archive.require(isinstance(sha, str) and archive.SHA.fullmatch(sha), "Invalid trusted package hash")
        cmd = [sys.executable, str(Path(__file__).with_name("archive.py")), "--archive",
               str(args.archive), "--id", identifier, args.action, "--sha256", sha]
        if args.action == "audit":
            archive.require(args.mirrors is not None, "Mirror configuration required")
            cmd += ["--mirrors", str(args.mirrors)]
        if subprocess.run(cmd).returncode:
            failed.append(identifier)
    if failed:
        event = {"event":"sanctuary.preservation.failed","action":args.action,"models":failed,"time":archive.now()}
        print(json.dumps(event), file=sys.stderr)
        if args.alert_command:
            subprocess.run(args.alert_command, input=archive.encoded(event), check=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
