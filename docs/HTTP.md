# 阶段接口

`POST /api/stages/<stage>` 接收 `multipart/form-data`。字段 `sample=dirty`、`sample=clean` 或 `file=<CSV>` 三选一。阶段为 `intake`、`prepare`、`calculate`、`policy`、`balance`。预览不入库。

`calculate` 起返回 `ledger`（模型、渠道汇总、逐转化分摊、`direct`、`no_touch`、`direct_only`）；`balance` 追加 `reconciliation`（逐条净额与渠道功劳、对平标志）、`issues`、`blocking`、`conflicts`、`window_gaps`、`unreconciled`、`signable`，以及专列清单 `balance.separate_records`。

`POST /api/runs` 接收同样的输入，执行全批并返回运行报告。`GET /api/runs` 返回最近 50 批。`GET /api/runs/<id>` 查询一批、当前复核状态与版本链 `versions`。

`PATCH /api/runs/<id>` 接收 `revision`、`status` 和 `note`。状态使用 `APPROVED` 或 `HELD`。冲突返回 409，客户端读取新版本后重试；批次存在阻断项时签发同样返回 409。

`GET /api/runs/<id>/evidence` 下载内含运行清单、血缘 `lineage`、版本链 `versions`、逐条对账 `reconciliation`、直达/无触点专列、阻断项、行号隔离、业务证据和复核信息的 JSON。

## 归因账字段

| 字段 | 含义 |
|---|---|
| `ledger.entries[].allocations` | 每个参与触点的 `share`、`credit_cents`、`rounding_cents` |
| `ledger.entries[].channels` | 该转化落到各渠道的功劳与触点键 |
| `ledger.entries[].direct` | 直达触点（不计渠道功劳） |
| `ledger.direct` / `ledger.direct_only` | 直达触点清单 / 仅直达触点的转化 |
| `ledger.no_touch` | 窗口内无合规触点的转化 |
| `reconciliation.entries[].delta_cents` | 净额减去渠道功劳后的差额（直达/无触点即整笔净额） |
| `reconciliation.entries[].separate_cents` | 进入直达/无触点专列的净额 |
| `reconciliation.balanced` | 逐条对平且全量守恒 |
| `blocking` | 挡住签发的记录键 |
