"""血缘变换表达式：结构化步骤、旧竖线格式解析与边界证据判定。

旧格式把步骤用竖线拼成一个字符串（``"trim|标准化"``）。这种格式没有转义，
一旦某一步表达式自身包含竖线（例如正则 ``^1(3|5|8)\\d{9}$``），回读时就无法
判断竖线是分隔符还是表达式内容。本模块因此把“能不能证明边界”显式建模：

* 新链路：调用方按步骤传入，逐条原样保存，不做任何拼接/切分；
* 旧链路：只有在没有歧义迹象时才按竖线切分，并且只标记为“推定边界”；
* 出现不闭合括号/引号、空段、悬挂转义等迹象时，不猜步骤，保留原文并说明原因。

所有解析结果都同时给出 ``证据核验``（可核验/不可核验）和 ``解析依据``，
供合并追溯日志与审计报表直接引用。
"""
from __future__ import annotations

import datetime
from typing import Any, Iterable

LEGACY_FORMAT = "旧竖线拼接"
STRUCTURED_FORMAT = "结构化"

PARSE_OK = "已迁移（边界为推定）"
PARSE_PROVEN = "已迁移（边界有证据）"
PARSE_UNPROVEN = "边界不可证明（保留原文）"
PARSE_STRUCTURED = "结构化写入"
PARSE_EMPTY = "空记录（无步骤）"

_PAIRS = {"(": ")", "[": "]", "{": "}", "（": "）", "【": "】", "《": "》"}
_CLOSERS = set(_PAIRS.values())
_QUOTES = {'"', "'"}


def make_step(index: int, value: Any, note: str | None = None) -> dict[str, Any]:
    """构造一个步骤；``值`` 原样保存，不裁剪、不改写。"""
    step: dict[str, Any] = {"顺序": index, "值": value}
    if note:
        step["说明"] = note
    return step


def normalize_steps(transformations: Iterable[Any] | str | None) -> list[dict[str, Any]]:
    """把多种入参归一成有序步骤列表，表达式内容逐字保留。

    - ``str``：视为**一条**表达式，绝不按竖线切分；
    - ``list``：按给定顺序逐条保存，元素可以是字符串或带 ``值/value`` 的字典。
    """
    if transformations is None:
        return []
    if isinstance(transformations, str):
        return [make_step(1, transformations)] if transformations != "" else []
    steps: list[dict[str, Any]] = []
    for item in transformations:
        if isinstance(item, dict):
            value = item.get(
                "值",
                item.get("value", item.get("表达式", item.get("expr", item.get("transformation")))),
            )
            note = item.get("说明", item.get("note"))
        else:
            value, note = item, None
        if value is None:
            continue
        steps.append(make_step(len(steps) + 1, value, note))
    return steps


def _unbalanced_fragment(fragment: str) -> bool:
    """判断片段里是否有跨片段才可能闭合的括号/引号。"""
    stack: list[str] = []
    quote: str | None = None
    escaped = False
    for char in fragment:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in _QUOTES:
            quote = char
            continue
        if char in _PAIRS:
            stack.append(_PAIRS[char])
            continue
        if char in _CLOSERS:
            if not stack or stack.pop() != char:
                return True
    # 片段末尾的转义符也可能吞掉了原本的分隔符
    return bool(stack) or quote is not None or escaped


def parse_legacy_transform(
    raw: Any,
    *,
    evidence_steps: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """解析一条旧竖线拼接的变换记录。

    ``evidence_steps`` 是迁移清册/人工确认提供的原步骤；一旦提供，
    解析边界就有了外部证据，结果标记为可核验。否则旧格式最多只能“推定”。
    """
    text = "" if raw is None else str(raw)
    result: dict[str, Any] = {
        "原文": text,
        "步骤": [],
        "解析状态": PARSE_EMPTY,
        "解析依据": "",
        "证据核验": "不可核验",
        "核验说明": "",
    }

    if evidence_steps is not None:
        steps = normalize_steps(evidence_steps)
        result.update({
            "步骤": steps,
            "解析状态": PARSE_PROVEN,
            "解析依据": (
                "旧格式为竖线拼接；采用迁移清册/人工确认提供的原始步骤，"
                f"共 {len(steps)} 步，顺序与表达式均有外部证据"
            ),
            "证据核验": "可核验",
            "核验说明": "步骤边界来自迁移清册，可用于合并证据核验",
        })
        return result

    if text == "":
        result.update({
            "解析依据": "旧记录为空，没有可迁移的变换步骤",
            "核验说明": "空记录不构成合并证据",
        })
        return result

    if "|" not in text:
        step = make_step(1, text)
        result.update({
            "步骤": [step],
            "解析状态": PARSE_PROVEN,
            "解析依据": "旧格式中不含竖线，原文即唯一一步，步骤值原样保留",
            "证据核验": "可核验",
            "核验说明": "没有分隔歧义，单步边界可证明",
        })
        return result

    fragments = text.split("|")
    ambiguous_reasons: list[str] = []
    if any(fragment == "" for fragment in fragments):
        ambiguous_reasons.append("切分后存在空段，原表达式可能含连续竖线")
    if any(_unbalanced_fragment(fragment) for fragment in fragments):
        ambiguous_reasons.append(
            "切分后出现括号或引号不闭合片段，说明至少一条表达式的竖线落在括号/引号内部"
        )
    if any(fragment.endswith("\\") and not fragment.endswith("\\\\") for fragment in fragments):
        ambiguous_reasons.append("切分后出现悬挂转义符，竖线可能原本被转义")

    if ambiguous_reasons:
        result.update({
            # 不猜步骤：结构化步骤留空，整条原文原样保留
            "步骤": [],
            "解析状态": PARSE_UNPROVEN,
            "解析依据": (
                "旧格式为未转义的竖线拼接；"
                + "；".join(ambiguous_reasons)
                + "；无法证明每一步的边界，因此保留原文整体，不迁移为猜测步骤"
            ),
            "证据核验": "不可核验",
            "核验说明": "旧格式无法回读步骤边界，需业务方补充迁移清册或人工确认后才能核验",
        })
        return result

    steps = [make_step(index + 1, fragment) for index, fragment in enumerate(fragments)]
    result.update({
        "步骤": steps,
        "解析状态": PARSE_OK,
        "解析依据": (
            "旧格式为未转义的竖线拼接；按竖线切分得到 "
            f"{len(steps)} 步，各片段括号/引号结构闭合、无空段；"
            "但旧格式本身不能证明竖线一定是分隔符，边界仅为推定"
        ),
        "证据核验": "不可核验",
        "核验说明": "步骤顺序可读，但旧格式无法排除表达式内部含竖线，需人工确认边界",
    })
    return result


def structured_transform_metadata(
    steps: list[dict[str, Any]],
    *,
    parse_basis: str | None = None,
    source_rule: str | None = None,
    field_format: str = STRUCTURED_FORMAT,
) -> dict[str, Any]:
    """结构化写入时随行保存的解析元数据。"""
    return {
        "变换格式": field_format,
        "存储格式": STRUCTURED_FORMAT,
        "解析状态": PARSE_STRUCTURED,
        "解析依据": parse_basis or (
            "新链路按步骤逐条写入，表达式原样保留，不经过竖线拼接，"
            f"共 {len(steps)} 步且顺序由写入方确定"
        ),
        "证据核验": "可核验",
        "核验说明": "每一步都有独立的值且顺序明确，可直接用于合并证据核验",
        "清洗规则": source_rule or "",
        "迁移时间": "",
    }


def display_text(steps: list[dict[str, Any]]) -> str:
    """结构化步骤的单行展示；使用箭头而不是竖线，避免再次产生分隔歧义。"""
    return " → ".join(str(step.get("值", "")) for step in steps)


def now_iso() -> str:
    return datetime.datetime.utcnow().isoformat()


def step_english_view(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给程序化消费方的英文步骤视图（中文键仍是权威来源）。"""
    view: list[dict[str, Any]] = []
    for step in steps:
        item = {"seq": step.get("顺序"), "value": step.get("值")}
        if step.get("说明"):
            item["note"] = step["说明"]
        view.append(item)
    return view
