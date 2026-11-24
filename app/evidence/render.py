import json


def artifact(run, versions=None):
    report = run["report"]
    packet = {
        "schema": "review-evidence/1",
        "manifest": report["manifest"],
        "lineage": report.get("lineage", {}),
        "versions": versions or [],
        "balance": report["balance"],
        "ledger": report.get("ledger", {}),
        "reconciliation": report.get("reconciliation", {}),
        "direct": report.get("direct", []),
        "direct_only": report.get("direct_only", []),
        "no_touch": report.get("no_touch", []),
        "issues": report.get("issues", []),
        "blocking": report.get("blocking", []),
        "cases": report["cases"],
        "intake": report["intake"],
        "review": {key: run[key] for key in ("status", "revision", "note", "reviewed")},
    }
    return (
        json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()
