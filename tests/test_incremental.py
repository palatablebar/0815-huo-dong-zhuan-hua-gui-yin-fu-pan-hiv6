import json

import pytest

from app.business import DomainIssue
from app.evidence.render import artifact
from app.review.service import execute, review


def edit(clean, old, new):
    text = clean.decode("utf-8")
    assert old in text
    return text.replace(old, new).encode("utf-8")


def test_same_source_rerun_adds_no_credit(store, clean):
    first = execute(store, clean)
    second = execute(store, clean)
    assert first == second and len(store.list()) == 1
    assert first["report"]["reconciliation"]["channel_credit_cents"] == 121


def test_rerun_after_update_keeps_old_version(store, clean):
    first = execute(store, clean)
    changed = edit(
        clean,
        "000201,0002,conversion,100,0,1,31,30,交接明细",
        "000201,0002,conversion,100,0,1,31,25,交接明细",
    )
    second = execute(store, changed)
    assert second["id"] != first["id"]
    assert second["report"]["manifest"]["parent"] == first["id"]
    assert [v["id"] for v in store.versions(second["id"])] == [second["id"], first["id"]]
    packet = json.loads(artifact(second, store.versions(second["id"])))
    assert packet["versions"][1]["sha256"] == first["report"]["manifest"]["sha256"]


def test_only_affected_conversion_is_recomputed(store, clean):
    first = execute(store, clean)
    changed = edit(
        clean,
        "000104,0001,touch,85,2,1,0,0,已对照来源",
        "000104,0001,touch,85,2,1,0,0,已对照来源\n000106,0001,touch,90,6,1,0,0,新增触点",
    )
    second = execute(store, changed)
    lineage = second["report"]["lineage"]
    assert lineage["parent"] == first["id"]
    assert lineage["recomputed"] == ["000101"]
    assert lineage["reused"] == ["000201"]
    entries = {entry["record"]: entry for entry in second["report"]["ledger"]["entries"]}
    assert entries["000201"]["carried"] is True
    assert entries["000201"]["carried_from"]["run_id"] == first["id"]
    assert entries["000101"]["carried"] is False
    assert [item["record"] for item in entries["000101"]["allocations"]] == [
        "000104",
        "000106",
    ]


def test_carried_entry_keeps_original_origin_across_generations(store, clean):
    first = execute(store, clean)
    gen1_text = edit(
        clean,
        "000202,0002,touch,70,3,1,0,0,复核底稿",
        "000202,0002,touch,71,3,1,0,0,复核底稿",
    )
    gen1 = execute(store, gen1_text)
    gen2_text = gen1_text.decode("utf-8").replace(
        "000202,0002,touch,71,3,1,0,0,复核底稿",
        "000202,0002,touch,72,3,1,0,0,复核底稿",
    )
    gen2 = execute(store, gen2_text.encode("utf-8"))
    carried = {
        e["record"]: e for e in gen2["report"]["ledger"]["entries"]
    }["000101"]
    assert carried["carried"] is True
    assert carried["carried_from"]["run_id"] == gen1["id"]
    assert carried["carried_from"]["origin_run_id"] == first["id"]
    assert [v["id"] for v in store.versions(gen2["id"])] == [
        gen2["id"],
        gen1["id"],
        first["id"],
    ]


def test_note_only_change_does_not_recompute(store, clean):
    first = execute(store, clean)
    changed = edit(clean, "交接明细", "交接明细已归档")
    second = execute(store, changed)
    assert second["id"] != first["id"]
    assert second["report"]["lineage"]["reused"] == ["000101", "000201"]
    assert second["report"]["lineage"]["recomputed"] == []


def test_recomputed_credit_is_reproducible(store, clean):
    first = execute(store, clean)
    changed = edit(
        clean,
        "000104,0001,touch,85,2,1,0,0,已对照来源",
        "000104,0001,touch,85,2,1,0,0,已对照来源\n000106,0001,touch,90,6,1,0,0,新增触点",
    )
    second = execute(store, changed)
    assert second["report"]["reconciliation"]["channel_credit_cents"] == 121
    cases = {case["case"]: case for case in second["report"]["cases"]}
    assert [a["credit_cents"] for a in cases["0001"]["attribution"]["allocations"]] == [
        45,
        45,
    ]
    assert cases["0002"]["reused"] is True
    assert first["report"]["reconciliation"]["channel_credit_cents"] == 121


def test_dropped_conversion_is_reported(store, clean):
    first = execute(store, clean)
    text = clean.decode("utf-8")
    lines = [line for line in text.splitlines() if not line.startswith("0002")]
    second = execute(store, "\n".join(lines).encode("utf-8") + b"\n")
    assert first["id"] != second["id"]
    assert second["report"]["lineage"]["dropped"] == ["000201"]
    assert second["report"]["lineage"]["reused"] == ["000101"]


def test_blocked_update_will_not_be_signable(store, clean):
    changed = edit(
        clean,
        "000104,0001,touch,85,2,1,0,0,已对照来源",
        "000104,0001,touch,85,2,1,0,0,已对照来源\nERR9,0001,touch,-,9,1,0,0,缺测",
    )
    run = execute(store, changed)
    assert run["report"]["balance"]["releasable"] is False
    assert "ERR9" in run["report"]["blocking"]
    with pytest.raises(DomainIssue, match="UNRESOLVED_ISSUES"):
        review(
            store, run["id"],
            dict(revision=0, status="APPROVED", note="尝试签发带阻断项的更新"),
        )
