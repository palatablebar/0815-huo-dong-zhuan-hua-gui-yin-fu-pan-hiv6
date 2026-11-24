from collections import Counter

# 直达与无触点进入具名专列：单独列示，净额另有专列承接，不算未完成项。
SEPARATE_STATUSES = {"DIRECT_ONLY", "NO_TOUCH"}


def balance(intake, cases):
    accounted = (
        intake["accepted"] + intake["rejected"] + intake["blank"] + intake["repeated"]
    )
    status = Counter(case["status"] for case in cases)
    ready = status.get("READY", 0)
    separate = sum(status.get(name, 0) for name in SEPARATE_STATUSES)
    observed = sum(len(case["records"]) for case in cases)
    issues = {
        name: count
        for name, count in sorted(status.items())
        if name not in {"READY", *SEPARATE_STATUSES}
    }
    return dict(
        input=intake["input"],
        accepted=intake["accepted"],
        isolated=intake["rejected"],
        ignored=intake["blank"] + intake["repeated"],
        accounted=accounted,
        balanced=accounted == intake["input"] and observed == intake["accepted"],
        ready=ready,
        separate_cases=separate,
        settled=ready,
        pending=len(cases) - ready,
        issues=issues,
        releasable=bool(cases)
        and ready == len(cases)
        and not issues
        and not intake["rejected"]
        and accounted == intake["input"]
        and observed == intake["accepted"],
    )
