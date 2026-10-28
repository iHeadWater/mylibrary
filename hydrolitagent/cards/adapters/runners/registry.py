"""Runner registry: a runner id is data, construction is one lookup.

The platform offers exactly two executors:

* ``in_session`` -- the current agent reads ``paper.md`` and writes
  ``response.json``; ``cards run prepare|finalize`` needs no API key;
* ``direct`` -- one direct call to an OpenAI-compatible API (DeepSeek by
  default), for when you want the card without an agent in the loop.

Adding another one means: write an adapter that implements
``ports.runner.CardRunner``, then register a factory here (one line).

Import contract: importing this module must not import any implementation. Each
factory imports its adapter inside the function body, so ``cards --help`` and
``cards ai-config`` stay fast and provider-free, and the dependency arrow stays
*adapters → registry*, never the other way at import time.

Factory contract: a factory receives keyword arguments and picks the ones it
understands. Unknown keywords are ignored on purpose so ``composition`` can pass
one fixed bag of dependencies to every runner without growing a per-runner
branch.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hydrolitagent.cards.ports.runner import CardRunner

RunnerFactory = Callable[..., CardRunner]

# Documented ids that cannot be built yet. They live outside ``ids()`` so the
# listing never promises a runner that ``create`` would reject.
_PLANNED: dict[str, str] = {}

_FACTORIES: dict[str, RunnerFactory] = {}


class RegistryError(ValueError):
    """Unknown, duplicated, reserved or not-yet-implemented runner id."""


def _normalize(runner_id: str) -> str:
    if not isinstance(runner_id, str) or not runner_id.strip():
        raise RegistryError("runner id 不能为空")
    return runner_id.strip().casefold()


def _available_text() -> str:
    available = "、".join(ids())
    planned = "、".join(f"{name}（未实现）" for name in planned_ids())
    return f"{available}" + (f"；计划中：{planned}" if planned else "")


def register(runner_id: str, factory: RunnerFactory, *, replace: bool = False) -> None:
    """Bind one id to a factory. Re-registering the same id is an error."""

    name = _normalize(runner_id)
    if not callable(factory):
        raise RegistryError(f"runner {name!r} 的 factory 必须可调用")
    if name in _PLANNED:
        raise RegistryError(
            f"{name!r} 已列为计划中的运行器：实现后再注册，不要用占位 factory 覆盖"
        )
    if name in _FACTORIES and not replace:
        raise RegistryError(f"runner 已注册：{name}；如需替换请传 replace=True")
    _FACTORIES[name] = factory


def unregister(runner_id: str) -> None:
    """Remove a registration; used by tests and plugin reloads."""

    name = _normalize(runner_id)
    if _FACTORIES.pop(name, None) is None:
        raise RegistryError(f"runner 未注册：{runner_id!r}")


def ids() -> tuple[str, ...]:
    """Every id ``create`` can currently build, sorted for stable output."""

    return tuple(sorted(_FACTORIES))


def planned_ids() -> tuple[str, ...]:
    return tuple(sorted(_PLANNED))


def create(runner_id: str, **kwargs: Any) -> CardRunner:
    """Build one runner, or fail with the list of ids that would have worked."""

    name = _normalize(runner_id)
    factory = _FACTORIES.get(name)
    if factory is None:
        if name in _PLANNED:
            raise RegistryError(
                f"运行器 {name!r} 尚未实现：{_PLANNED[name]}；当前可用：{_available_text()}"
            )
        raise RegistryError(
            f"未注册的运行器：{runner_id!r}；当前可用：{_available_text()}"
        )
    runner = factory(**kwargs)
    if not getattr(runner, "runner_id", None):
        raise RegistryError(f"runner {name!r} 的 factory 返回了没有 runner_id 的对象")
    return runner


# --------------------------------------------------------------------------------------
# Built-in factories. Importing this module binds function objects only; the
# adapter modules are imported on first use.
# --------------------------------------------------------------------------------------


def _direct_runner(**options: Any) -> CardRunner:
    from hydrolitagent.cards.adapters.runners.direct import DirectRunner

    return DirectRunner(
        base_url=options.get("base_url"),
        api_key=options.get("api_key"),
        model=options.get("model"),
        max_input_tokens=options.get("max_input_tokens"),
        max_output_tokens=options.get("max_output_tokens"),
        transport=options.get("transport"),
    )


def _in_session_runner(**options: Any) -> CardRunner:
    from hydrolitagent.cards.adapters.runners.in_session import InSessionRunner

    # A file-based runner has nothing to configure: the run directory arrives on
    # the request, not in the factory options.
    return InSessionRunner()


register("direct", _direct_runner)
register("in_session", _in_session_runner)


__all__ = [
    "RegistryError",
    "RunnerFactory",
    "create",
    "ids",
    "planned_ids",
    "register",
    "unregister",
]
