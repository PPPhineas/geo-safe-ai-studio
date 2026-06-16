"""第 6 环:AI 研判(语义交模型)。

构建 prompt → 调 LLM(低温 + JSON 模式)→ 解析为研判 JSON。
prompt 见 app.prompts.risk_judgement;输出 schema 见 风险研判提示词.md 第七部分。

铁律:模型只做语义研判,严禁计算/改写数字(铁律 1);每条点位结论须带 monitor_point_code(铁律 2);
地形相关须含来源标注(铁律 3)。这些在 validation 环节强制校验,不靠模型自觉。
"""

from __future__ import annotations

import json
import re

from app.clients.llm import LLMClient
from app.prompts.risk_judgement import SYSTEM_PROMPT, build_user_prompt

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class JudgementParseError(ValueError):
    """模型返回无法解析为 JSON。"""


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    text = _FENCE_RE.sub("", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 兜底:截取第一个 { 到最后一个 }
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise JudgementParseError(f"研判输出无法解析为 JSON:{raw[:200]}")


def run_judgement(placeholders: dict, client: LLMClient | None = None) -> dict:
    """调用 LLM 产出研判 JSON(未校验;校验在 validation)。"""
    client = client or LLMClient()
    user = build_user_prompt(placeholders)
    raw = client.judge(SYSTEM_PROMPT, user)
    return _parse_json(raw)
