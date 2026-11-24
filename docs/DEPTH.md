# 活动转化归因复盘规则登记

- 规模：中型

## 功能模块

| 模块 | 动作 | 接口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 样例采信 | 预览并定位坏行 | `POST /api/stages/intake` | `app/intake/service.py` | `tests/test_intake.py` |
| M2 触点筛选 | 检查参与条件与窗口 | `POST /api/stages/prepare` | `app/modules/prepare.py` | `tests/test_prepare.py` |
| M3 多触点归因 | 查看等分结果与渠道账 | `POST /api/stages/calculate` | `app/modules/calculate.py`、`app/modules/ledger.py` | `tests/test_calculate.py`、`tests/test_ledger.py` |
| M4 归因对账 | 查看逐条对平与签收判定 | `POST /api/stages/policy` | `app/modules/policy.py` | `tests/test_policy.py` |
| M5 运行对账 | 对照输入、采信、专列与阻断项 | `POST /api/stages/balance` | `app/modules/reconcile.py`、`app/modules/ledger.py` | `tests/test_reconcile.py` |
| M6 批次复核 | 执行批次并签发或暂缓 | `POST /api/runs、PATCH /api/runs/<id>` | `app/review/service.py` | `tests/test_review.py` |
| M7 证据交付 | 下载复核清单与版本链 | `GET /api/runs/<id>/evidence` | `app/evidence/render.py` | `tests/test_evidence.py` |

## 归因规则

归因模型登记为 `equal-split-v1`（`app/config.py`）。

- 回望窗口 `[minute - lookback, minute)`：含起点、排除转化时刻；`consent = 1`；`channel != 0`。
- 净额按参与触点等分，整数余数按记录键升序补齐，`credit_cents` 之和恒等于净额。
- 逐条对平：每次转化的渠道功劳合计必须恰好等于净额，任何渠道功劳不得高于净额。
- 直达记录与无触点案例不占渠道功劳，单独列出；渠道功劳为 0 与净额不相等，同样记为未对平并挡住签发，净额以专列字段留在账内。

## 复发与版本

- 同一来源按内容摘要寻址批次 ID，重跑命中同一账本，不会新增功劳。
- 来源更新后，按单个转化的业务指纹（不含 `note`）判断是否受影响：指纹不变则结转旧账并标注 `carried_from`，指纹变化才重算。
- 历史批次连同旧版证据保留，`manifest.parent` 指向基线上游，证据包里的 `versions` 给出完整版本链。
- 直达与无触点的净额在证据包（`direct` / `no_touch` / `direct_only`）与界面专列中单独可查，并作为未对平项列出记录键。

## 阻断口径

冲突记录、窗口缺口、未对平（渠道功劳 ≠ 净额，含直达与无触点）与参考值差异都会列出记录键；`balance.releasable` 为假时 `PATCH` 签发返回 409。

## 输入陷阱

| 编号 | 规则 | 处理 | 测试 |
|---|---|---|---|
| TRAP-02 | 去除 BOM | `app/intake/reader.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-03 | 按逻辑记录读取引号内换行 | `app/intake/reader.py` | `tests/test_intake.py::test_quoted_newline_is_one_logical_record` |
| TRAP-04 | 重复表头计入忽略行 | `app/intake/service.py` | `tests/test_intake.py::test_repeated_header_is_counted` |
| TRAP-05 | 异常列数隔离 | `app/intake/schema.py` | `tests/test_intake.py::test_extra_column_is_isolated` |
| TRAP-06 | 归一化全角数字和千分位 | `app/intake/numeric.py` | `tests/test_intake.py::test_full_width_and_grouping_are_canonical` |
| TRAP-07 | 空值行隔离 | `app/intake/numeric.py` | `tests/test_intake.py::test_sentinel_keeps_row_out_of_total` |
| TRAP-08 | 记录键保留前导零 | `app/intake/schema.py` | `tests/test_intake.py::test_bom_preserves_identifier` |
| TRAP-14 | 冲突版本都进入隔离 | `app/intake/resolve.py` | `tests/test_intake.py::test_duplicate_conflict_removes_both_copies` |
| TRAP-16 | 引号未闭合时拒收文件 | `app/intake/reader.py` | `tests/test_intake.py::test_unclosed_quote_invalidates_source` |
| TRAP-18 | 区分空文件、全空白和仅表头 | `app/intake/reader.py` | `tests/test_intake.py::test_empty_states_have_distinct_causes` |
| TRAP-26 | 拒绝旧版本复核 | `app/review/store.py` | `tests/test_review.py::test_review_optimistic_lock` |

## 领域反例

归因窗口含回溯起点，排除转化时刻。仅接受同意标志为 1 的非直达触点。等分余数按记录键裁决。

逐组预期结论见 `tests/test_policy.py`，计算过程证据见 `tests/test_calculate.py`，账本口径见 `tests/test_ledger.py`。
