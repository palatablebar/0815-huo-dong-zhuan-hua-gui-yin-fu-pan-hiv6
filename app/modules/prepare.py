"""触点筛选：只保留同意标志为 1 且落在回溯窗口内的触点。"""

from app.business import by_kind, prepared, single


def prepare(rows):
    event = single(rows, "conversion")
    target = single(rows, "expected")["value_cents"]
    minute = event["minute"]
    start = minute - event["lookback"]
    touches = sorted(
        by_kind(rows, "touch"), key=lambda row: (row["minute"], row["record"])
    )
    eligible = [
        row
        for row in touches
        if row["consent"] == 1 and start <= row["minute"] < minute
    ]
    details = {
        "conversion_min": minute,
        "lookback_min": event["lookback"],
        "window": {
            "start": start,
            "end": minute,
            "start_inclusive": True,
            "end_exclusive": True,
        },
        "eligible_records": [row["record"] for row in eligible],
        "participating_records": [
            row["record"] for row in eligible if row["channel"] != 0
        ],
        "direct_records": [row["record"] for row in eligible if row["channel"] == 0],
    }
    return prepared(
        len(eligible),
        details,
        {
            "event": event,
            "target": target,
            "touches": touches,
            "eligible": eligible,
        },
    )
