COLUMNS = ("minute", "channel", "consent", "value_cents", "lookback")
KINDS = ("touch", "conversion", "expected")
PROJECT = {
    "name": "活动转化归因复盘",
    "actor": "营销数据分析员",
    "stages": [
        ("intake", "样例采信"),
        ("prepare", "触点筛选"),
        ("calculate", "多触点归因"),
        ("policy", "归因对账"),
        ("balance", "运行对账"),
    ],
    "chart": "渠道归因分布",
}
