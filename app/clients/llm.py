"""LLM 客户端封装(DeepSeek,OpenAI 兼容)。

调用要点(见 风险研判提示词.md「调用与落地要点」):低温(0–0.3)+ JSON 模式,保证可解析与稳定。
参数来自 config.Settings(llm_base_url / llm_api_key / llm_model / llm_temperature / llm_json_mode)。
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator

import httpx

from app.config import Settings, get_settings


class LLMError(RuntimeError):
    """LLM 调用失败(网络 / 非 2xx / 响应结构异常)。"""


class LLMClient:
    """LLM 调用封装(DeepSeek /chat/completions)。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        base = self.settings.llm_base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=base,
            timeout=httpx.Timeout(120.0),
            headers={
                "Authorization": f"Bearer {self.settings.llm_api_key}",
                "Content-Type": "application/json",
            },
        )

    def judge(self, system: str, user: str, *, retries: int = 2) -> str:
        """发送 system + user,返回模型原始文本(期望为 JSON 字符串)。

        低温 + JSON 模式;失败重试。DeepSeek 的 JSON 模式要求消息中出现 "json" 字样,
        SYSTEM_PROMPT 第 6 条「只输出 JSON」已满足。
        """
        payload = {
            "model": self.settings.llm_model,
            "temperature": self.settings.llm_temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self.settings.llm_json_mode:
            payload["response_format"] = {"type": "json_object"}
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                resp = self._client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                last_exc = exc
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"LLM 调用失败(重试 {retries} 次后): {last_exc}") from last_exc

    def judge_stream(self, system: str, user: str) -> Iterator[tuple[str, str]]:
        """流式调用,逐块产出 ``(kind, text)``。

        kind ∈ {"reasoning", "content"}:reasoning=模型思考过程(若 model 支持,如
        DeepSeek 推理模型的 reasoning_content);content=最终回答(JSON 文本,需上层拼接解析)。
        失败抛 LLMError。
        """
        payload = {
            "model": self.settings.llm_model,
            "temperature": self.settings.llm_temperature,
            "stream": True,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self.settings.llm_json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            with self._client.stream(
                "POST", "/chat/completions", json=payload, timeout=httpx.Timeout(300.0)
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except ValueError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    reasoning = delta.get("reasoning_content")
                    if reasoning:
                        yield ("reasoning", reasoning)
                    content = delta.get("content")
                    if content:
                        yield ("content", content)
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM 流式调用失败: {exc}") from exc


