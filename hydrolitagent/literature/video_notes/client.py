"""DeepSeek 接口封装：文本与视觉两个入口，统一退避重试与用量记账。

走 OpenAI 兼容协议。``thinking`` 显式关掉 —— 这条流水线全是「按素材整理」的
活，思考模式只会让 50 分钟的片子跑成几个小时，质量并无提升。
"""

from __future__ import annotations

import base64
import io
import os
import re
import sys
import time
from pathlib import Path

from openai import OpenAI

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"

_BRACKETED = re.compile(r"^\[.*\]$")


def sanitize_no_proxy(environ=None) -> list[str]:
    """把 ``NO_PROXY`` 里带方括号的 IPv6 项去掉，返回被删掉的项。

    为什么必须剔：httpx 0.28 把 ``[::1]`` 这类项拼成通配模式 ``all://*[::1]``，
    而 ``httpx.Client(mounts=...)`` 又会把每个 key 当 URL 再解析一次，于是
    ``:1]`` 被当成端口，抛 ``InvalidURL: Invalid port``。openai 2.x 恰好把
    ``get_environment_proxies()`` 的结果原样交给 ``httpx.Client``，所以只要
    ``NO_PROXY`` 里有方括号 IPv6，``OpenAI(...)`` 连构造都构造不出来。

    去掉是安全的：同一份列表里通常已经有 ``::1``，回环照样绕过代理。
    改了 ``os.environ`` 不写回，只影响本进程。
    """
    env = os.environ if environ is None else environ
    removed: list[str] = []
    for key in ("NO_PROXY", "no_proxy"):
        raw = env.get(key)
        if not raw:
            continue
        kept: list[str] = []
        for item in raw.split(","):
            item = item.strip()
            if not item:
                continue
            if _BRACKETED.match(item):
                removed.append(item)
                continue
            kept.append(item)
        env[key] = ",".join(kept)
    return removed


class DeepSeek:
    """一次运行一个实例。``usage`` 累计的用量最后写进 ``run.json``。

    空响应不算成功 —— 视觉调用偶发返回 ``None``，早期没有这道检查时，
    一次偶发失败会把整轮 50 分钟的活毁掉。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 1200,
    ) -> None:
        key = (api_key or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
        if not key:
            raise RuntimeError(
                "缺少 DEEPSEEK_API_KEY：写进 .env 或设为环境变量（见 .env.example）"
            )
        # 必须在构造 OpenAI 之前：方括号 IPv6 会让 httpx 在解析 mounts 时崩掉
        dropped = sanitize_no_proxy()
        if dropped:
            print(
                f"  已从 NO_PROXY 去掉 {', '.join(dropped)}"
                "（方括号 IPv6 会触发 httpx 的 URL 解析 bug，详见 client.py 注释）",
                file=sys.stderr,
                flush=True,
            )
        self.client = OpenAI(
            base_url=base_url or os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL,
            api_key=key,
            timeout=timeout,
        )
        # 刻意不读 DEEPSEEK_MODEL：那个变量在 .env.example 里默认指向
        # deepseek-chat，而看图这条路要 flash。要换模型请显式传参。
        self.model = model or DEFAULT_MODEL
        self.usage: list[dict] = []

    # ---------------------------------------------------------------- 底层
    def _call(
        self,
        messages: list,
        max_tokens: int,
        temperature: float,
        json_mode: bool = False,
        tries: int = 4,
    ):
        kw = {"response_format": {"type": "json_object"}} if json_mode else {}
        last: Exception | None = None
        for k in range(tries):
            t0 = time.monotonic()
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    extra_body={"thinking": {"type": "disabled"}},
                    **kw,
                )
                if resp is None or not getattr(resp, "choices", None):
                    raise RuntimeError("接口返回空响应")
                u = resp.usage.model_dump() if getattr(resp, "usage", None) else {}
                self.usage.append(
                    {
                        "elapsed": round(time.monotonic() - t0, 1),
                        "finish": resp.choices[0].finish_reason,
                        "prompt": u.get("prompt_tokens"),
                        "completion": u.get("completion_tokens"),
                    }
                )
                return resp
            except Exception as exc:  # noqa: BLE001
                last = exc
                wait = 2**k
                print(
                    f"  接口异常（第 {k + 1}/{tries} 次）：{exc!r}，{wait}s 后重试",
                    flush=True,
                )
                time.sleep(wait)
        raise RuntimeError(f"接口连续 {tries} 次失败：{last!r}")

    # ---------------------------------------------------------------- 入口
    def ask(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
        json_mode: bool = False,
    ) -> str:
        resp = self._call(
            [{"role": "user", "content": prompt}], max_tokens, temperature, json_mode
        )
        return (resp.choices[0].message.content or "").strip()

    def ask_vision(self, parts: list, max_tokens: int, temperature: float = 0) -> str:
        """``parts`` 是 text / image_url 混排的 content 数组。"""
        resp = self._call(
            [{"role": "user", "content": parts}], max_tokens, temperature, True
        )
        return (resp.choices[0].message.content or "").strip()

    # ---------------------------------------------------------------- 记账
    def summary(self) -> dict:
        return {
            "calls": len(self.usage),
            "total_prompt": sum(u["prompt"] or 0 for u in self.usage),
            "total_completion": sum(u["completion"] or 0 for u in self.usage),
        }


def data_uri(path: Path, max_side: int = 640) -> str:
    """图片 → data URI。

    长边压到 ``max_side``：视觉调用按图计费，原图既贵又不会更准 —— 需要看清的是
    「画面里是什么图表/公式」，不是像素。
    """
    from PIL import Image

    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
