"""多触点归因账的确定性工具：业务指纹、整数分摊、逐条对平与阻断项。

记账口径（同时满足渠道与财务约束）：

* 参与条件：同意标志为 1、非直达、落在回溯窗口内（含起点、排除转化
  时刻）。同一笔净额在这些触点之间等分，整数分按记录键补齐。
* 财务约束：每次转化的渠道功劳合计必须等于净额，且不得高于净额 ——
  逐条对平。任何渠道功劳都不得高于净额。
* 直达记录与无触点案例没有渠道功劳，净额无法落到渠道，因此单独列示；
  渠道功劳（0）与净额不相等，逐条对平不成立，同样列出记录键并挡住
  签发。净额以 `direct_cents` / `no_touch_cents` 留在账内，不会消失。
* 阻断项：冲突记录（重复记录版本不一致等隔离行）、窗口缺口（回溯起点
  早于来源可观测起点）、未对平与参考值差异，都会列出记录键并挡住签发。
"""

import json
from hashlib import sha256

from app.config import ATTRIBUTION_MODEL, RULE_VERSION

BUSINESS_FIELDS = (
    "record",
    "case",
    "kind",
    "minute",
    "channel",
    "consent",
    "value_cents",
    "lookback",
)

# 只有这些类别会挡住签发。
BLOCKING = {
    "CONFLICT",
    "ISOLATED",
    "WINDOW_GAP",
    "UNRECONCILED",
    "MISMATCH",
    "CASE_ERROR",
    "NO_TOUCH",
    "DIRECT_ONLY",
}

# 具名专列：单独列示、不占渠道功劳；净额留在专列即未与渠道对平。
SEPARATE = {"DIRECT_ONLY", "NO_TOUCH"}

# 未对平原因：直达与无触点的渠道功劳为 0，净额没有落到渠道。
UNDERFUNDED = {
    "NO_TOUCH": "窗口内没有同意触点，净额留在无触点专列，渠道功劳为 0",
    "DIRECT_ONLY": "只有直达触点，净额留在直达专列，渠道功劳为 0",
}


def fingerprint(rows):
    """判断一次转化是否受源数据更新影响；说明列 note 不参与业务指纹。"""
    payload = [
        {key: row[key] for key in BUSINESS_FIELDS}
        for row in sorted(rows, key=lambda row: (row["record"], row["kind"]))
    ]
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return sha256(canonical.encode()).hexdigest()


def allocate(net_cents, touches, conversion_minute):
    """把一笔净额等分给参与触点。

    最大余数按记录键升序补齐，保证整数分不丢不增、且重跑结果稳定；
    share 明示名义份额，credit_cents 是实际入账分，rounding_cents 标记
    因取整多得的 1 分。
    """
    ordered = sorted(touches, key=lambda touch: touch["record"])
    if not ordered:
        return []
    base, remainder = divmod(net_cents, len(ordered))
    allocations = []
    for index, touch in enumerate(ordered):
        credit = base + (1 if index < remainder else 0)
        allocations.append(
            {
                "record": touch["record"],
                "channel": touch["channel"],
                "minute": touch["minute"],
                "minutes_before": conversion_minute - touch["minute"],
                "share": {"numerator": 1, "denominator": len(ordered)},
                "credit_cents": credit,
                "rounding_cents": credit - base,
            }
        )
    return allocations


def channel_summary(allocations):
    """把触点入账汇总为渠道账，按渠道号升序。"""
    grouped = {}
    for item in allocations:
        channel = grouped.setdefault(
            item["channel"],
            {"channel": item["channel"], "credit_cents": 0, "touches": []},
        )
        channel["credit_cents"] += item["credit_cents"]
        channel["touches"].append(item["record"])
    return sorted(grouped.values(), key=lambda item: item["channel"])


def reconcile(entries):
    """逐条对平并汇总渠道账。

    逐条对平只看渠道功劳：每次转化的渠道功劳合计必须恰好等于净额，且
    不得高于净额。直达/无触点的渠道功劳为 0、净额进入具名专列，因此
    记为未对平并挡住签发；净额仍逐条可见，不会在账外消失。
    """
    rows = []
    for entry in entries:
        net = entry["net_cents"]
        credit = entry["channel_credit_cents"]
        direct = entry["direct_cents"]
        no_touch = entry["no_touch_cents"]
        separate = direct + no_touch
        allocated = credit + separate
        # 逐条对平：渠道功劳必须恰好等于净额，且任何渠道不得高于净额。
        # 直达/无触点的渠道功劳为 0，除非净额为 0，否则一律记为未对平。
        row_reconciled = 0 <= credit <= net and credit == net
        rows.append(
            {
                "record": entry["record"],
                "case": entry["case"],
                "mode": entry["mode"],
                "net_cents": net,
                "channel_credit_cents": credit,
                "direct_cents": direct,
                "no_touch_cents": no_touch,
                "separate_cents": separate,
                "allocated_cents": allocated,
                # 差额口径：尚未落到渠道的净额（渠道功劳为 0 时即整笔净额）。
                "delta_cents": net - credit,
                "channel_not_above_net": credit <= net,
                "reconciled": row_reconciled,
            }
        )
    attributed = [row for row in rows if row["mode"] == "MULTI_TOUCH"]
    direct = [row for row in rows if row["mode"] == "DIRECT_ONLY"]
    no_touch = [row for row in rows if row["mode"] == "NO_TOUCH"]
    channel_net = sum(row["net_cents"] for row in attributed)
    channel_credit = sum(row["channel_credit_cents"] for row in attributed)
    direct_net = sum(row["net_cents"] for row in direct)
    no_touch_net = sum(row["net_cents"] for row in no_touch)
    total_net = sum(row["net_cents"] for row in rows)
    separate_net = direct_net + no_touch_net
    unreconciled = sorted(row["record"] for row in rows if not row["reconciled"])
    channel_reconciled = channel_credit == channel_net
    conserved = channel_credit + separate_net == total_net
    return {
        "model": ATTRIBUTION_MODEL,
        "rule_version": RULE_VERSION,
        "conversions": len(rows),
        "attributed_conversions": len(attributed),
        "direct_conversions": len(direct),
        "no_touch_conversions": len(no_touch),
        "total_net_cents": total_net,
        "net_cents": total_net,
        "attributed_net_cents": channel_net,
        "channel_net_cents": channel_net,
        "channel_credit_cents": channel_credit,
        "direct_net_cents": direct_net,
        "no_touch_net_cents": no_touch_net,
        "separate_cents": separate_net,
        "allocated_cents": channel_credit + separate_net,
        # 差额口径：可归因渠道净额中尚未拿到渠道功劳的部分。
        "delta_cents": channel_net - channel_credit,
        "channel_not_above_net": all(
            row["channel_not_above_net"] for row in rows
        ),
        "channel_reconciled": channel_reconciled,
        "conserved": conserved,
        "balanced": bool(rows)
        and not unreconciled
        and channel_credit == total_net,
        "entries": rows,
        "unreconciled": unreconciled,
    }


def direct_records(entries):
    """直达触点记录：窗口内外都列，明确不计渠道功劳。"""
    records = []
    for entry in entries:
        for touch in entry.get("direct", []):
            records.append(
                {
                    "record": touch["record"],
                    "conversion": entry["record"],
                    "case": entry["case"],
                    "minute": touch["minute"],
                    "minutes_before": touch.get("minutes_before"),
                    "channel": 0,
                    "eligible": bool(touch.get("in_window"))
                    and touch.get("consent") == 1,
                    "credited": False,
                    "reason": "DIRECT_TOUCH",
                }
            )
    return sorted(records, key=lambda item: (item["conversion"], item["record"]))


def no_touch_records(entries):
    """无合规触点的转化：整笔净额进入未归因专列。"""
    return [
        {
            "record": entry["record"],
            "conversion": entry["record"],
            "case": entry["case"],
            "net_cents": entry["net_cents"],
            "expected_cents": entry["expected_cents"],
            "excluded": entry.get("excluded", []),
            "reason": "NO_ELIGIBLE_TOUCH",
        }
        for entry in entries
        if entry["mode"] == "NO_TOUCH"
    ]


def direct_only_records(entries):
    """只有直达触点的转化：净额进入直达专列。"""
    return [
        {
            "record": entry["record"],
            "conversion": entry["record"],
            "case": entry["case"],
            "net_cents": entry["net_cents"],
            "direct": entry.get("direct", []),
            "reason": "DIRECT_ONLY",
        }
        for entry in entries
        if entry["mode"] == "DIRECT_ONLY"
    ]


def build_issues(intake, entries, reconciliation, cases):
    """把问题落到记录键上；只有 BLOCKING 类别挡住签发。

    直达与无触点的净额进入具名专列，既列示也视为未对平：渠道功劳为 0，
    无法与净额逐条相等，因此同样挡住签发。
    """
    issues = []
    for row in reconciliation.get("entries", []):
        if row["reconciled"]:
            continue
        issues.append(
            {
                "kind": row["mode"] if row["mode"] in UNDERFUNDED else "UNRECONCILED",
                "record": row["record"],
                "case": row["case"],
                "mode": row["mode"],
                "net_cents": row["net_cents"],
                "channel_credit_cents": row["channel_credit_cents"],
                "separate_cents": row["separate_cents"],
                "delta_cents": row["delta_cents"],
                "detail": UNDERFUNDED.get(
                    row["mode"], "渠道功劳合计不等于转化净额"
                ),
            }
        )
    for row in intake.get("isolation", []):
        issues.append(
            {
                "kind": "CONFLICT"
                if row["reason"] == "DUPLICATE_CONFLICT"
                else "ISOLATED",
                "record": row["record"],
                "case": row["case"],
                "line": row["line"],
                "reason": row["reason"],
            }
        )
    for entry in entries:
        if entry.get("window_gap"):
            issues.append(
                {
                    "kind": "WINDOW_GAP",
                    "record": entry["record"],
                    "case": entry["case"],
                    "window": entry.get("window"),
                    "coverage_start": entry.get("coverage_start"),
                    "detail": "回溯窗口早于来源可观测起点",
                }
            )
        if entry.get("status") == "MISMATCH":
            issues.append(
                {
                    "kind": "MISMATCH",
                    "record": entry["record"],
                    "case": entry["case"],
                    "net_cents": entry["net_cents"],
                    "expected_cents": entry["expected_cents"],
                    "detail": "转化净额与参考值不一致",
                }
            )
    with_ledger = {entry["case"] for entry in entries}
    for case in cases:
        if case["case"] in with_ledger:
            continue
        issues.append(
            {
                "kind": "CASE_ERROR",
                "record": case["records"][0]
                if case.get("records")
                else case["case"],
                "case": case["case"],
                "records": list(case.get("records", [])),
                "reason": case.get("status"),
            }
        )
    seen, unique = set(), []
    for issue in sorted(
        issues,
        key=lambda row: (
            row["kind"] not in BLOCKING,
            row["kind"],
            row["record"],
            row.get("line", 0),
        ),
    ):
        key = (issue["kind"], issue["record"], issue.get("line"), issue.get("reason"))
        if key in seen:
            continue
        seen.add(key)
        issue["blocking"] = issue["kind"] in BLOCKING
        unique.append(issue)
    blocking = sorted({issue["record"] for issue in unique if issue["blocking"]})
    separate = sorted(
        row["record"]
        for row in reconciliation.get("entries", [])
        if row["mode"] in SEPARATE
    )
    return unique, blocking, separate


def categories(issues):
    """按类别列出仍会挡住签发的记录键，便于逐项核对。"""
    wanted = {
        "conflict_records": {"CONFLICT"},
        "window_gap_records": {"WINDOW_GAP"},
        # 直达与无触点的渠道功劳为 0，无法与净额逐条相等，同属未对平。
        "unreconciled_records": {"UNRECONCILED", "NO_TOUCH", "DIRECT_ONLY"},
        "isolated_records": {"ISOLATED"},
        "mismatch_records": {"MISMATCH"},
    }
    return {
        name: sorted(
            {
                issue["record"]
                for issue in issues
                if issue["kind"] in kinds and issue["blocking"]
            }
        )
        for name, kinds in wanted.items()
    }
