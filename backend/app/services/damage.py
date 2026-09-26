"""残损登记业务规则：定责口径、状态流转、字段校验与筛选都收在这里。

定责结论（责任方、残损类型判定、定责依据）全系统只有这一份判定逻辑：
列表、详情、统计都经由 build_conclusion 取同一份结果，前端只负责展示，
不再各自计算，避免两边口径漂移。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "damage"
REQUIRED_FIELDS = ["残损编号", "关联箱号", "残损类型"]
STATUS_ORDER = ["待定责", "已定责", "处理中", "已闭环", "已挂起"]
ACTION_RULES = {"确认定责": "已定责", "提交闭环": "已闭环", "挂起记录": "已挂起"}
NEGATIVE_ACTIONS = []
CLOSED_STATUS = "已闭环"

# 定责依据只保留这一份：责任方按残损部位判定，残损类型按登记描述归并。
LIABILITY_RULES = [
    ("箱顶", "码头作业方", "箱顶损伤多为吊具起落碰刮，归码头作业责任"),
    ("侧壁", "码头作业方", "箱侧壁损伤多为装卸机械碰刮，归码头作业责任"),
    ("箱门", "运输方", "箱门、锁杆损伤多为集卡运输途中碰撞，归运输责任"),
    ("锁杆", "运输方", "箱门、锁杆损伤多为集卡运输途中碰撞，归运输责任"),
    ("箱底", "堆场方", "箱底损伤多为堆场堆放或叉车作业造成，归堆场责任"),
]
TYPE_RULES = [
    ("湿", "湿损", "进水或受潮造成的残损"),
    ("锈", "锈蚀", "自然氧化锈蚀，属正常损耗"),
    ("凹", "凹陷变形", "外力碰撞造成的结构性凹陷"),
    ("破", "破损穿孔", "箱体破裂、穿孔类残损"),
    ("污", "污染", "货物泄漏或外部沾染造成的污染"),
]
UNKNOWN_LIABILITY = ("待定", "现有信息不足以判定责任方，需补充残损部位说明")
UNKNOWN_TYPE = ("一般残损", "登记描述未匹配到具体残损类型，按一般残损归档")


def _match_rules(rules: list[tuple[str, str, str]], text: str, fallback: tuple[str, str]) -> tuple[str, str]:
    for keyword, value, basis in rules:
        if keyword in text:
            return value, basis
    return fallback


def build_conclusion(entry: dict[str, Any]) -> dict[str, Any]:
    """输出一条残损记录的定责结论，列表、详情、统计都从这里取。

    取数优先级：已存档的定责结论 > 历史定责记录原样沿用 > 按定责依据给出规则建议。
    已存档与历史结论一律原样返回，不用新口径重算，保证原有的定责记录照旧。
    """
    stored = entry.get("定责结论")
    if stored:
        return dict(stored)
    if entry.get("status") != STATUS_ORDER[0]:
        return {
            "责任方": str(entry.get("责任方") or UNKNOWN_LIABILITY[0]),
            "残损类型判定": str(entry.get("残损类型") or UNKNOWN_TYPE[0]),
            "定责依据": "历史定责记录，沿用登记时的责任方与残损类型",
            "结论来源": "历史存档",
            "定责时间": entry.get("发现时间"),
        }
    part = str(entry.get("残损部位") or "")
    dtype = str(entry.get("残损类型") or "")
    party, party_basis = _match_rules(LIABILITY_RULES, part, UNKNOWN_LIABILITY)
    type_name, type_basis = _match_rules(TYPE_RULES, dtype, UNKNOWN_TYPE)
    return {
        "责任方": party,
        "残损类型判定": type_name,
        "定责依据": f"{party_basis}；{type_basis}",
        "结论来源": "规则建议",
        "定责时间": None,
    }


class DamageService:
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
        return [self._with_conclusion(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self._with_conclusion(row) if row is not None else None

    def summary(self) -> dict[str, Any]:
        """统计口径与列表、详情一致：责任方分布直接汇总 build_conclusion 的结果。"""
        by_status = {status: 0 for status in STATUS_ORDER}
        by_party: dict[str, int] = {}
        closed_this_month = 0
        month = date.today().strftime("%Y-%m")
        for row in store.rows(MODULE):
            status = str(row.get("status") or STATUS_ORDER[0])
            by_status[status] = by_status.get(status, 0) + 1
            party = str(build_conclusion(row)["责任方"])
            by_party[party] = by_party.get(party, 0) + 1
            if status == CLOSED_STATUS and str(row.get("闭环时间") or "").startswith(month):
                closed_this_month += 1
        return {"状态统计": by_status, "责任方分布": by_party, "本月闭环数": closed_this_month}

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._with_conclusion(entry), []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"残损记录 {entry_id} 不存在或已归档"
        if entry.get("status") == CLOSED_STATUS:
            return None, f"残损记录 {entry_id} 已闭环，定责结论已归档，不能再改回{STATUS_ORDER[0]}或执行其他动作"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于残损登记可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        message = f"残损记录已{action}"
        if action == "确认定责":
            if self._store_conclusion(entry, values or {}):
                message = "残损记录已确认定责，重复提交只保留最新一条结论"
        if target == CLOSED_STATUS:
            entry["闭环时间"] = date.today().isoformat()
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return self._with_conclusion(entry), message

    def _with_conclusion(self, row: dict[str, Any]) -> dict[str, Any]:
        """读侧统一附上定责结论；只读不改库，结论落库只发生在确认定责时。"""
        return {**row, "定责结论": build_conclusion(row)}

    def _store_conclusion(self, entry: dict[str, Any], values: dict[str, Any]) -> bool:
        """把定责结论落到记录上：重复提交只保留最新一条，返回是否覆盖了旧结论。"""
        suggested = build_conclusion(entry)
        party = str(values.get("责任方") or suggested["责任方"]).strip()
        type_name = str(values.get("残损类型判定") or suggested["残损类型判定"]).strip()
        overwritten = bool(entry.get("定责结论"))
        entry["定责结论"] = {
            "责任方": party,
            "残损类型判定": type_name,
            "定责依据": str(values.get("定责依据") or suggested["定责依据"]),
            "结论来源": "人工确认",
            "定责时间": datetime.now().isoformat(timespec="seconds"),
        }
        # 行上的责任方字段同步成结论口径，避免列表字段与结论各说各话
        entry["责任方"] = party
        return overwritten
