"""阶段流水线：采信 → 筛选 → 多触点归因 → 对账 → 运行账。"""

import copy

from app.business import DomainIssue, single
from app.intake.service import inspect
from app.modules import ledger
from app.modules.calculate import attribution, measure_from
from app.modules.grouping import case_groups
from app.modules.policy import policy
from app.modules.prepare import prepare
from app.modules.reconcile import balance

# 来源时间轴从 0 分钟起算；回溯起点小于 0 说明窗口跨出可观测范围。
COVERAGE_START = 0


def conversion_of(rows):
    return single(rows, "conversion")


def evaluate(rows, stage, coverage_start=COVERAGE_START, baseline=None):
    case = {
        "case": rows[0]["case"],
        "records": [r["record"] for r in rows],
        "status": "READY",
    }
    fingerprint = ledger.fingerprint(rows)
    case["fingerprint"] = fingerprint
    try:
        conversion = conversion_of(rows)
        reused = (baseline or {}).get(conversion["record"])
        if stage >= 2:
            case["prep"], payload = prepare(rows)
        if stage >= 3:
            if (
                reused is not None
                and reused["fingerprint"] == fingerprint
                and reused["attribution"].get("coverage_start") == coverage_start
            ):
                entry = copy.deepcopy(reused["attribution"])
                origin = (
                    entry.get("carried_from", {}).get("origin_run_id")
                    or reused["run_id"]
                )
                for stale in ("status", "carried", "recompute_reason", "fingerprint"):
                    entry.pop(stale, None)
                entry["carried_from"] = {
                    "run_id": reused["run_id"],
                    "revision": reused["revision"],
                    "fingerprint": fingerprint,
                    "origin_run_id": origin,
                }
                case["reused"] = True
                case["recompute_reason"] = "FINGERPRINT_UNCHANGED"
            else:
                entry = attribution(
                    payload["event"],
                    payload["target"],
                    payload["touches"],
                    coverage_start=coverage_start,
                )
                case["reused"] = False
                case["recompute_reason"] = (
                    "SOURCE_CHANGED" if reused is not None else "NEW_CONVERSION"
                )
            entry["fingerprint"] = fingerprint
            case["attribution"] = entry
            if entry["mode"] == "MULTI_TOUCH":
                case["measure"] = measure_from(entry)
        if stage >= 4:
            if "measure" in case:
                case.update(policy(case["measure"]))
            elif "attribution" in case:
                case["status"] = case["attribution"]["mode"]
                case["delta"] = None
    except DomainIssue as error:
        case["status"] = error.code
    return case


def ledger_entries(cases):
    entries = []
    for case in cases:
        row = case.get("attribution")
        if not row:
            continue
        row = dict(row)
        row["status"] = case["status"]
        row["carried"] = bool(case.get("reused"))
        row["recompute_reason"] = case.get("recompute_reason")
        entries.append(row)
    return entries


def materialize(cases):
    entries = ledger_entries(cases)
    return {
        "model": ledger.ATTRIBUTION_MODEL,
        "coverage_start": COVERAGE_START,
        "conversions": len(entries),
        "entries": entries,
        "channels": ledger.channel_summary(
            [item for entry in entries for item in entry["allocations"]]
        ),
        "direct": ledger.direct_records(entries),
        "no_touch": ledger.no_touch_records(entries),
        "direct_only": ledger.direct_only_records(entries),
    }


def run(data, stage=5, coverage_start=COVERAGE_START, baseline=None):
    intake = inspect(data)
    output = {"intake": {k: v for k, v in intake.items() if k != "rows"}}
    if stage == 1:
        return output
    cases = [
        evaluate(rows, stage, coverage_start, baseline)
        for _, rows in case_groups(intake["rows"])
    ]
    output["cases"] = cases
    if stage >= 3:
        books = materialize(cases)
        output["ledger"] = books
        output["attribution"] = books
        output["direct"] = books["direct"]
        output["no_touch"] = books["no_touch"]
        output["direct_records"] = books["direct"]
        output["no_touch_records"] = books["no_touch"]
        output["direct_only"] = books["direct_only"]
    if stage >= 5:
        checks = balance(intake, cases)
        entries = ledger_entries(cases)
        reconciliation = ledger.reconcile(entries)
        blockers, blocking, separate = ledger.build_issues(
            intake, entries, reconciliation, cases
        )
        checks["reconciliation"] = reconciliation
        checks["blockers"] = blockers
        checks["blocking"] = blocking
        checks["issue_records"] = blocking
        checks["separate_records"] = separate
        checks.update(ledger.categories(blockers))
        checks["balanced_ledger"] = reconciliation["balanced"]
        checks["releasable"] = (
            checks["releasable"]
            and reconciliation["balanced"]
            and not blockers
            and not blocking
        )
        output["balance"] = checks
        output["reconciliation"] = reconciliation
        output["issues"] = blockers
        output["blockers"] = blockers
        output["blocking"] = blocking
        output["unreconciled"] = reconciliation["unreconciled"]
        output["window_gaps"] = checks["window_gap_records"]
        output["conflicts"] = checks["conflict_records"]
        output["signable"] = checks["releasable"]
    return output
