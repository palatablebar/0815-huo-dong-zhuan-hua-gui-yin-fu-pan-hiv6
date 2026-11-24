"""多触点归因计算：可解释、整数分、逐条守恒。"""

from app.business import measured
from app.modules import ledger


def window_of(event):
    minute = event["minute"]
    lookback = event["lookback"]
    return minute - lookback, minute


def classify(event, touches):
    """把同一转化下的触点分成窗口内可参与、窗口外与未同意三类。"""
    start, end = window_of(event)
    eligible, excluded = [], []
    for touch in sorted(touches, key=lambda row: (row["minute"], row["record"])):
        if touch["minute"] < start or touch["minute"] >= end:
            excluded.append(
                {
                    "record": touch["record"],
                    "channel": touch["channel"],
                    "minute": touch["minute"],
                    "consent": touch["consent"],
                    "reason": "OUTSIDE_WINDOW",
                }
            )
        elif touch["consent"] != 1:
            excluded.append(
                {
                    "record": touch["record"],
                    "channel": touch["channel"],
                    "minute": touch["minute"],
                    "consent": touch["consent"],
                    "reason": "CONSENT_NOT_GRANTED",
                }
            )
        else:
            eligible.append(touch)
    return eligible, excluded


def window_gap(start, coverage_start=0):
    """回溯窗口早于来源可观测起点时，存在看不见的归因缺口。"""
    return start < coverage_start


def attribution(event, target, touches, coverage_start=0):
    """计算一笔转化净额在各渠道触点上的分摊与对平结果。

    只有“同意且在回溯窗口内”的非直达触点参与渠道分摊；直达触点
    （channel=0）单列、不占渠道功劳；无合规触点时整笔列入无触点专列。
    直达/无触点的渠道功劳为 0，`reconciled` 为假，由运行对账挡住签发。
    """
    minute = event["minute"]
    start, end = window_of(event)
    eligible, excluded = classify(event, touches)
    channel_touches = [row for row in eligible if row["channel"] != 0]
    direct_touches = [
        {
            "record": row["record"],
            "minute": row["minute"],
            "minutes_before": minute - row["minute"],
            "in_window": start <= row["minute"] < end,
            "consent": row["consent"],
        }
        for row in sorted(touches, key=lambda item: (item["minute"], item["record"]))
        if row["channel"] == 0
    ]
    net = event["value_cents"]
    allocations = ledger.allocate(net, channel_touches, minute)
    channels = ledger.channel_summary(allocations)
    credit = sum(item["credit_cents"] for item in allocations)
    if channel_touches:
        mode = "MULTI_TOUCH"
    elif any(item["in_window"] and item["consent"] == 1 for item in direct_touches):
        mode = "DIRECT_ONLY"
    else:
        mode = "NO_TOUCH"
    direct_cents = net if mode == "DIRECT_ONLY" else 0
    no_touch_cents = net if mode == "NO_TOUCH" else 0
    return {
        "record": event["record"],
        "case": event["case"],
        "mode": mode,
        "net_cents": net,
        "expected_cents": target,
        "window": {
            "start": start,
            "end": end,
            "start_inclusive": True,
            "end_exclusive": True,
        },
        "coverage_start": coverage_start,
        "window_gap": window_gap(start, coverage_start),
        "participating": [
            {
                "record": row["record"],
                "channel": row["channel"],
                "minute": row["minute"],
                "minutes_before": minute - row["minute"],
                "consent": row["consent"],
            }
            for row in sorted(channel_touches, key=lambda item: item["record"])
        ],
        "eligible_records": sorted(row["record"] for row in channel_touches),
        "direct": direct_touches,
        "excluded": sorted(excluded, key=lambda item: item["record"]),
        "allocations": allocations,
        "channels": channels,
        "channel_credit_cents": credit,
        "direct_cents": direct_cents,
        "no_touch_cents": no_touch_cents,
        "separate_cents": direct_cents + no_touch_cents,
        "allocated_cents": credit + direct_cents + no_touch_cents,
        "within_net": credit <= net,
        "reconciled": credit == net and 0 <= credit <= net,
    }


def measure_from(result):
    """从分摊结果生成末次触点证据，并挂载完整归因账。"""
    allocations = result.get("allocations", [])
    anchor = max(
        allocations, key=lambda row: (row["minute"], row["record"]), default=None
    )
    evidence = {
        "channel": anchor["channel"] if anchor else 0,
        "chosen_touch": anchor["record"] if anchor else None,
        "elapsed_min": (
            result["window"]["end"] - anchor["minute"] if anchor else None
        ),
    }
    measurement = measured(
        result["net_cents"], result["expected_cents"], "分", evidence
    )
    measurement["attribution"] = result
    return measurement


def compute(payload, coverage_start=0):
    """供外部直接调用：返回带 attribution 的测算结果。

    既接受 prepare 产出的字典载荷，也接受旧式 (event, valid, target)
    三元组；两种形态都按同一套多触点规则计算。
    """
    if isinstance(payload, dict):
        data = payload
    else:
        event, valid, target = payload
        data = {
            "event": event,
            "target": target,
            "touches": valid,
            "eligible": valid,
        }
    return measure_from(
        attribution(
            data["event"],
            data["target"],
            data["touches"],
            coverage_start=coverage_start,
        )
    )
