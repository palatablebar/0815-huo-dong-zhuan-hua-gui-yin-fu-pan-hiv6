import json

import pytest

from app.business import DomainIssue
from app.evidence.render import artifact
from app.intake.schema import HEADER
from app.modules import ledger
from app.modules.pipeline import run
from app.review.service import execute, review
from conftest import csv_data

TOUCH = ["T1", "C1", "touch", "10", "2", "1", "0", "0", "触点"]
DIRECT = ["T2", "C1", "touch", "20", "0", "1", "0", "0", "直达"]
CONVERSION = ["V1", "C1", "conversion", "40", "0", "1", "100", "30", "转化"]
EXPECTED = ["E1", "C1", "expected", "0", "0", "0", "100", "0", "参考"]


def case_out(data, code="C1"):
    return next(c for c in run(data)["cases"] if c["case"] == code)


def test_equal_split_is_integer_and_ordered():
    touches = [
        {"record": "T2", "channel": 4, "minute": 10},
        {"record": "T1", "channel": 3, "minute": 12},
    ]
    allocations = ledger.allocate(41, touches, 20)
    assert [item["record"] for item in allocations] == ["T1", "T2"]
    assert [item["credit_cents"] for item in allocations] == [21, 20]
    assert sum(item["credit_cents"] for item in allocations) == 41


def test_only_consented_in_window_channel_touches_participate():
    rows = [
        CONVERSION,
        ["T1", "C1", "touch", "10", "2", "0", "0", "0", "未同意"],
        ["T2", "C1", "touch", "9", "0", "1", "0", "0", "直达"],
        ["T3", "C1", "touch", "39", "7", "1", "0", "0", "窗口内"],
        ["T4", "C1", "touch", "40", "9", "1", "0", "0", "转化时刻排除"],
        ["T5", "C1", "touch", "9", "8", "1", "0", "0", "窗口外"],
        EXPECTED,
    ]
    entry = case_out(csv_data(rows))["attribution"]
    assert entry["mode"] == "MULTI_TOUCH"
    assert entry["eligible_records"] == ["T3"]
    assert entry["channel_credit_cents"] == 100
    assert entry["net_cents"] == 100


def test_window_includes_lookback_start_and_excludes_conversion_minute():
    rows = [
        ["V1", "C1", "conversion", "30", "0", "1", "100", "20", "转化"],
        ["T1", "C1", "touch", "10", "2", "1", "0", "0", "窗口起点"],
        ["T2", "C1", "touch", "30", "3", "1", "0", "0", "转化时刻"],
        ["E1", "C1", "expected", "0", "0", "0", "100", "0", "参考"],
    ]
    entry = case_out(csv_data(rows))["attribution"]
    assert entry["eligible_records"] == ["T1"]
    assert {item["record"]: item["reason"] for item in entry["excluded"]} == {
        "T2": "OUTSIDE_WINDOW"
    }


def test_direct_touch_is_listed_but_not_credited():
    rows = [CONVERSION, DIRECT, TOUCH, EXPECTED]
    report = run(csv_data(rows))
    entry = case_out(csv_data(rows))["attribution"]
    assert entry["channel_credit_cents"] == 100
    assert [item["record"] for item in report["direct"]] == ["T2"]
    assert report["direct"][0]["credited"] is False


def test_direct_only_conversion_is_separate_and_uncredited():
    rows = [CONVERSION, DIRECT, EXPECTED]
    report = run(csv_data(rows))
    entry = case_out(csv_data(rows))["attribution"]
    assert entry["mode"] == "DIRECT_ONLY"
    assert report["direct_only"][0]["record"] == "V1"
    assert entry["channel_credit_cents"] == 0
    row = report["reconciliation"]["entries"][0]
    assert row["reconciled"] is False and row["separate_cents"] == 100
    assert "V1" in report["blocking"]
    assert "V1" in report["balance"]["separate_records"]
    assert report["direct_only"][0]["reason"] == "DIRECT_ONLY"
    assert report["balance"]["releasable"] is False


def test_no_touch_conversion_is_separate():
    rows = [CONVERSION, ["T1", "C1", "touch", "10", "2", "0", "0", "0", "未同意"], EXPECTED]
    report = run(csv_data(rows))
    entry = case_out(csv_data(rows))["attribution"]
    assert entry["mode"] == "NO_TOUCH"
    assert [item["record"] for item in report["no_touch"]] == ["V1"]
    assert report["no_touch"][0]["excluded"][0]["reason"] == "CONSENT_NOT_GRANTED"
    row = report["reconciliation"]["entries"][0]
    assert row["reconciled"] is False and row["no_touch_cents"] == 100
    assert "V1" in report["blocking"]
    assert "V1" in report["balance"]["separate_records"]
    assert report["no_touch"][0]["reason"] == "NO_ELIGIBLE_TOUCH"
    assert report["balance"]["releasable"] is False


def test_every_conversion_reconciles_to_net():
    rows = [
        CONVERSION, TOUCH, DIRECT,
        ["V2", "C2", "conversion", "40", "0", "1", "41", "30", "转化2"],
        ["T6", "C2", "touch", "32", "4", "1", "0", "0", "触点6"],
        ["T7", "C2", "touch", "33", "5", "1", "0", "0", "触点7"],
        ["E2", "C2", "expected", "0", "0", "0", "41", "0", "参考2"],
        EXPECTED,
    ]
    report = run(csv_data(rows))
    entries = report["reconciliation"]["entries"]
    assert [row["channel_credit_cents"] for row in entries] == [100, 41]
    assert all(row["reconciled"] for row in entries)
    assert report["reconciliation"]["channel_credit_cents"] == 141
    assert report["reconciliation"]["total_net_cents"] == 141


def test_channel_credit_never_exceeds_net():
    rows = [
        CONVERSION,
        ["T1", "C1", "touch", "30", "2", "1", "0", "0", "触点1"],
        ["T2", "C1", "touch", "31", "3", "1", "0", "0", "触点2"],
        ["T3", "C1", "touch", "32", "4", "1", "0", "0", "触点3"],
        EXPECTED,
    ]
    entry = case_out(csv_data(rows))["attribution"]
    assert entry["channel_credit_cents"] <= entry["net_cents"]
    assert sum(item["credit_cents"] for item in entry["allocations"]) == 100
    assert entry["channel_credit_cents"] == 100


def test_unreconciled_entry_blocks_signing():
    reconciliation = ledger.reconcile(
        [
            dict(
                record="V1",
                case="C1",
                mode="MULTI_TOUCH",
                net_cents=100,
                channel_credit_cents=90,
                direct_cents=0,
                no_touch_cents=0,
            )
        ]
    )
    issues, blocking, _ = ledger.build_issues(
        dict(isolation=[]), [], reconciliation, []
    )
    assert reconciliation["unreconciled"] == ["V1"]
    assert blocking == ["V1"]
    assert any(issue["kind"] == "UNRECONCILED" for issue in issues)


def test_conflict_and_window_gap_block_signing():
    rows = [
        ["V1", "C1", "conversion", "5", "0", "1", "100", "30", "窗口跨出起点"],
        ["T1", "C1", "touch", "4", "2", "1", "0", "0", "触点"],
        ["E1", "C1", "expected", "0", "0", "0", "100", "0", "参考"],
        ["D1", "C2", "conversion", "10", "0", "1", "10", "5", "冲突"],
        ["D1", "C2", "conversion", "11", "0", "1", "10", "5", "冲突"],
    ]
    report = run(csv_data(rows))
    assert "V1" in report["window_gaps"]
    assert "D1" in report["conflicts"]
    assert "V1" in report["blocking"] and "D1" in report["blocking"]
    assert report["balance"]["releasable"] is False


def test_rerun_same_source_does_not_add_credit(store, clean):
    first = execute(store, clean)
    second = execute(store, clean)
    assert first["id"] == second["id"] and len(store.list()) == 1
    entries = first["report"]["reconciliation"]["entries"]
    assert sum(row["channel_credit_cents"] for row in entries) == sum(
        row["channel_credit_cents"] for row in second["report"]["reconciliation"]["entries"]
    )


def test_source_update_recomputes_only_affected_conversion(store, clean):
    first = execute(store, clean)
    original = sum(
        row["channel_credit_cents"]
        for row in first["report"]["reconciliation"]["entries"]
    )
    text = clean.decode("utf-8")
    text = text.replace(
        "000202,0002,touch,70,3,1,0,0,复核底稿",
        "000202,0002,touch,70,3,1,0,0,复核底稿\n000205,0002,touch,80,7,1,0,0,补充触点",
    ).replace("000203,0002,touch,100,2,1,0,0,补录记录\n", "")
    updated = execute(store, text.encode("utf-8"))
    lineage = updated["report"]["lineage"]
    assert lineage["parent"] == first["id"]
    assert lineage["reused"] == ["000101"]
    assert lineage["recomputed"] == ["000201"]
    entries = updated["report"]["reconciliation"]["entries"]
    assert all(row["reconciled"] for row in entries)
    assert sum(row["channel_credit_cents"] for row in entries) == original


def test_old_evidence_is_retained_in_version_chain(store, clean):
    first = execute(store, clean)
    text = clean.decode("utf-8").replace(
        "000202,0002,touch,70,3,1,0,0,复核底稿",
        "000202,0002,touch,70,3,1,0,0,复核底稿\n000205,0002,touch,80,7,1,0,0,补充触点",
    )
    updated = execute(store, text.encode("utf-8"))
    versions = store.versions(updated["id"])
    assert [item["id"] for item in versions] == [updated["id"], first["id"]]
    assert versions[0]["parent"] == first["id"]
    packet = json.loads(artifact(updated, versions))
    assert packet["lineage"]["parent"] == first["id"]
    assert packet["manifest"]["parent"] == first["id"]
    assert [item["id"] for item in packet["versions"]] == [updated["id"], first["id"]]


def test_blocked_batch_cannot_be_signed(store):
    blocked = csv_data(
        [
            ["V1", "C1", "conversion", "5", "0", "1", "100", "30", "缺口"],
            ["T1", "C1", "touch", "4", "2", "1", "0", "0", "触点"],
            ["E1", "C1", "expected", "0", "0", "0", "100", "0", "参考"],
        ]
    )
    run_record = execute(store, blocked)
    with pytest.raises(DomainIssue, match="UNRESOLVED_ISSUES"):
        review(
            store, run_record["id"],
            dict(revision=0, status="APPROVED", note="尝试签发缺口批次"),
        )
