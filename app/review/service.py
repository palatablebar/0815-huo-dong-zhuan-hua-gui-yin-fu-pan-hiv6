from datetime import datetime, timezone
from hashlib import sha256
from time import monotonic

from app.business import DomainIssue
from app.config import ATTRIBUTION_MODEL, RULE_VERSION
from app.intake.service import inspect
from app.modules import ledger
from app.modules.pipeline import run


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def conversions_of(data):
    """只做采信解析，拿到本次来源里的转化记录键。"""
    try:
        intake = inspect(data)
    except DomainIssue:
        return []
    return sorted(
        row["record"] for row in intake["rows"] if row["kind"] == "conversion"
    )


def baseline_from(previous):
    """取基线批次的逐转化业务指纹，用于只重算受影响的转化。"""
    if not previous:
        return None, None
    entries = previous["report"].get("ledger", {}).get("entries", [])
    mapping = {
        entry["record"]: {
            "fingerprint": entry.get("fingerprint"),
            "attribution": entry,
            "coverage_start": entry.get("coverage_start"),
            "run_id": previous["id"],
            "revision": previous["revision"],
        }
        for entry in entries
    }
    return mapping, previous["id"]


def execute(store, data):
    start = monotonic()
    fingerprint = sha256(data).hexdigest()
    # 以“规则版本 + 来源内容”寻址：同一来源重跑命中同一账本，不新增功劳；
    # 规则升级后同一来源会生成新账本并可追溯到旧版。
    run_id = sha256(
        f"{RULE_VERSION}:{ATTRIBUTION_MODEL}:{fingerprint}".encode()
    ).hexdigest()
    try:
        existing = store.load(run_id)
        return existing
    except DomainIssue as error:
        if error.code != "RUN_NOT_FOUND":
            raise
    previous = store.baseline_for(conversions_of(data), run_id)
    baseline, parent = baseline_from(previous)
    report = run(data, coverage_start=0, baseline=baseline)
    entries = report.get("ledger", {}).get("entries", [])
    carried = sorted(entry["record"] for entry in entries if entry["carried"])
    recomputed = sorted(
        entry["record"] for entry in entries if not entry["carried"]
    )
    dropped = sorted(set(baseline or {}) - {entry["record"] for entry in entries})
    report["lineage"] = {
        "parent": parent,
        "baseline_sha256": (previous or {})
        .get("report", {})
        .get("manifest", {})
        .get("sha256"),
        "reused": carried,
        "recomputed": recomputed,
        "dropped": dropped,
        "model": ATTRIBUTION_MODEL,
    }
    report["manifest"] = dict(
        sha256=fingerprint,
        version=RULE_VERSION,
        model=ATTRIBUTION_MODEL,
        parent=parent,
        created=now(),
        duration_ms=round((monotonic() - start) * 1000, 3),
        bytes=len(data),
        run_id=run_id,
    )
    return store.register(run_id, report)


def review(store, run_id, values):
    if not isinstance(values, dict):
        raise DomainIssue("REVIEW_FIELDS")
    revision, status, note = (values.get(key) for key in ("revision", "status", "note"))
    if (
        type(revision) is not int
        or revision < 0
        or status not in ("APPROVED", "HELD")
        or not isinstance(note, str)
        or not (3 <= len(note.strip()) <= 200)
    ):
        raise DomainIssue("REVIEW_FIELDS")
    current = store.load(run_id)
    if revision != current["revision"]:
        raise DomainIssue("STALE_REVIEW")
    if current["status"] == "APPROVED":
        raise DomainIssue("RUN_FINALIZED")
    if status == "APPROVED" and not current["report"]["balance"]["releasable"]:
        raise DomainIssue("UNRESOLVED_ISSUES")
    return store.revise(run_id, revision, status, note.strip(), now())
