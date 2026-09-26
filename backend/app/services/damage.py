"""残损登记业务规则：状态流转、字段校验与筛选口径都收在这里。

定责口径只有这一份：``derive_liability`` 是责任方与残损类型判定的唯一实现，
列表、详情、统计、导出都经过它产出结论，前端只展示不重算，因此各端口径一致。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "damage"
REQUIRED_FIELDS = ["残损编号", "关联箱号", "残损类型"]
STATUS_ORDER = ["待定责", "已定责", "处理中", "已闭环", "已挂起"]
CLOSED_STATUS = "已闭环"
PENDING_STATUS = "待定责"
ACTION_RULES = {"确认定责": "已定责", "提交闭环": "已闭环", "挂起记录": "已挂起"}
NEGATIVE_ACTIONS = []

# 定责依据表：残损类型按关键字归一后落到这里的标准类型与责任方。
# 要调整定责口径，只改这一张表，列表/详情/统计自动跟着走，不会再两边漂。
LIABILITY_RULES: list[dict[str, str]] = [
    {
        "match": "凹陷|变形|弯折|破洞|刮擦|划伤|破裂",
        "残损类型": "机械损伤",
        "责任方": "码头作业方",
        "定责依据": "箱体凹陷、变形、破损属装卸机械作业所致，归码头作业方",
    },
    {
        "match": "渗漏|污染|受潮|污损|油污|腐蚀",
        "残损类型": "货物污染",
        "责任方": "货主方",
        "定责依据": "渗漏污染源于货物自身包装或装载不当，归货主方",
    },
    {
        "match": "水渍|水湿|进水|锈蚀|锈穿",
        "残损类型": "水渍锈蚀",
        "责任方": "船公司",
        "定责依据": "运输途中进水受潮导致水湿锈蚀，归船公司",
    },
    {
        "match": "短缺|灭失|短少|丢失|箱封|封条",
        "残损类型": "短少灭失",
        "责任方": "理货方",
        "定责依据": "数量短少、封条异常属交接清点环节责任，归理货方",
    },
]

# 各状态允许执行的动作；不在表里的动作一律拦下。
STATUS_ACTIONS: dict[str, list[str]] = {
    "待定责": ["确认定责"],
    # 已定责仍允许再次确认定责：重复提交只保留最新一条结论（见 confirm_liability）。
    "已定责": ["确认定责", "提交闭环", "挂起记录"],
    "处理中": ["提交闭环"],
    "已挂起": ["确认定责"],
    "已闭环": [],
}


def derive_liability(raw_type: str | None) -> dict[str, str]:
    """唯一定责入口：把登记的残损类型归一，推出标准类型、责任方与依据。

    识别不出来时返回空责任方，调用方据此保持「待定责」，不臆断责任归属。
    """
    text = str(raw_type or "").strip()
    for rule in LIABILITY_RULES:
        if any(keyword in text for keyword in rule["match"].split("|")):
            return {
                "标准残损类型": rule["残损类型"],
                "责任方": rule["责任方"],
                "定责依据": rule["定责依据"],
            }
    return {"标准残损类型": "未识别类型", "责任方": "", "定责依据": ""}


class DamageService:
    # ---- 读取：所有出口都过 present_entry，保证定责结论只有一份口径 ----

    def present_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """给一条原始记录附上统一口径的定责结论。

        已落定的结论（历史记录或此前确认过的）原样沿用，不重算；
        尚未定责的记录用 ``derive_liability`` 现算，识别不出即保持待定责。
        """
        view = dict(entry)
        status = str(entry.get("status") or PENDING_STATUS)
        stored_party = str(entry.get("定责责任方") or "").strip()
        # 历史记录没有定责责任方字段，但状态已走过定责，按「照旧」沿用其责任方列。
        legacy = not stored_party and status in ("已定责", "处理中", "已闭环", "已挂起")
        finalized = bool(stored_party) or legacy
        if stored_party:
            derived = {
                "标准残损类型": entry.get("标准残损类型") or entry.get("残损类型") or "",
                "责任方": stored_party,
                "定责依据": entry.get("定责依据", ""),
            }
        elif legacy:
            derived = {
                "标准残损类型": entry.get("残损类型") or "历史类型",
                "责任方": str(entry.get("责任方") or "").strip() or "历史沿用",
                "定责依据": str(entry.get("定责依据") or "").strip() or "历史定责记录，结论照旧沿用",
            }
        else:
            derived = derive_liability(entry.get("残损类型"))
        view["标准残损类型"] = derived["标准残损类型"]
        view["责任方"] = derived["责任方"] or "待定责"
        view["定责依据"] = derived["定责依据"]
        if not finalized:
            # 尚未确认定责：列表可预览统一口径建议，但结论状态仍是待定责，需人工确认。
            view["定责状态"] = PENDING_STATUS
            view["定责结论"] = PENDING_STATUS
            view["建议责任方"] = derived["责任方"]
        else:
            view["定责状态"] = "已定责"
            view["定责结论"] = f"{derived['标准残损类型']}，责任方：{derived['责任方']}"
            view["建议责任方"] = ""
        view["定责时间"] = entry.get("定责时间")
        view["定责版本"] = entry.get("定责版本", 0)
        view["定责说明"] = entry.get("定责说明") or ("历史定责记录，结论照旧沿用" if legacy else "")
        return view

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("残损编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = [self.present_entry(row) for row in rows[start:start + size]]
        return page_rows, total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self.present_entry(entry) if entry is not None else None

    def stats(self) -> dict[str, int]:
        """统计也取统一口径：直接数同一份结论，避免列表和看板对不上。"""
        rows = store.rows(MODULE)
        views = [self.present_entry(row) for row in rows]
        today = date.today()
        month_prefix = today.strftime("%Y-%m")
        return {
            "待定责记录": sum(1 for view in views if view["定责状态"] == PENDING_STATUS),
            "处理中残损": sum(1 for view in views if view["status"] == "处理中"),
            "本月闭环数": sum(
                1
                for view in views
                if view["status"] == CLOSED_STATUS
                and str(view.get("闭环时间") or "").startswith(month_prefix)
            ),
        }

    # ---- 写入 ----

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 登记时允许顺手带上残损部位等补充字段，但定责仍以服务端判定为准。
        for field in ["残损部位", "发现时间", "登记人员"]:
            if str(values.get(field) or "").strip():
                entry[field] = values[field]
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self.present_entry(entry), []

    def confirm_liability(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str, str]:
        """确认定责：服务端按统一口径重算，结论以服务端为准。

        返回 (记录, 提示级别, 说明)。同一记录重复提交只保留最新一条结论，
        旧结论被版本号覆盖；已闭环的记录不允许退回待定责。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, "error", f"残损记录 {entry_id} 不存在或已归档"
        if entry.get("status") == CLOSED_STATUS:
            return None, "error", "残损记录已闭环，定责结论已锁定，不能再改回待定责"

        # 以本次提交的残损类型更新原始事实，再由唯一口径推导结论。
        raw_type = str(values.get("残损类型") or entry.get("残损类型") or "").strip()
        if not raw_type:
            return None, "error", "缺少残损类型，无法按统一口径判定责任方"
        entry["残损类型"] = raw_type
        if str(values.get("残损部位") or "").strip():
            entry["残损部位"] = values["残损部位"]

        derived = derive_liability(raw_type)
        if not derived["责任方"]:
            return None, "error", f"残损类型「{raw_type}」匹配不到定责依据，保持待定责，请补充更明确的残损描述"

        client_party = str(values.get("责任方") or "").strip()
        repeated = bool(entry.get("定责责任方"))
        if client_party and client_party != derived["责任方"]:
            note = (
                f"提交的责任方「{client_party}」与统一口径不符，"
                f"已按服务端结论「{derived['责任方']}」定责：{derived['定责依据']}"
            )
        elif repeated:
            note = f"重复提交已覆盖上一条结论，最新责任方为「{derived['责任方']}」"
        else:
            note = f"已按统一口径定责：{derived['定责依据']}"

        entry["标准残损类型"] = derived["标准残损类型"]
        entry["定责责任方"] = derived["责任方"]
        entry["定责依据"] = derived["定责依据"]
        entry["定责时间"] = date.today().isoformat()
        entry["定责版本"] = int(entry.get("定责版本", 0)) + 1
        entry["定责说明"] = note
        entry["status"] = "已定责"
        entry["pending"] = True
        return self.present_entry(entry), "warn" if client_party and client_party != derived["责任方"] else "ok", note

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str, str]:
        """执行状态流转动作，返回 (记录, 提示级别, 说明)。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, "error", f"残损记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, "error", f"动作「{action}」不属于残损登记可执行范围"

        status = str(entry.get("status") or "")
        if status == CLOSED_STATUS:
            return None, "error", "残损记录已闭环，结论已锁定，不能再执行任何状态变更"
        if action not in STATUS_ACTIONS.get(status, []):
            return None, "error", f"残损记录当前为「{status}」，不能执行「{action}」"

        # 确认定责是带判定口径的动作，交给专门方法走统一逻辑。
        if action == "确认定责":
            return self.confirm_liability(entry_id, values or {})

        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, "error", f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target not in (CLOSED_STATUS, STATUS_ORDER[-1])
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if target == CLOSED_STATUS:
            entry["闭环时间"] = date.today().isoformat()
        return self.present_entry(entry), "ok", f"残损记录已{action}"
