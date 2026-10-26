"""scholars 配置加载与校验。

API key 只从环境变量读取，绝不写进 TOML 或输出。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from hydrolitagent._config import PROJECT_ROOT, load_toml

from .errors import ConfigError

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "scholars.toml"

# OpenAlex 当前的作品类型（2026-10）。未知类型直接报错，避免静默漏统计。
VALID_WORK_TYPES = frozenset(
    {
        "article",
        "book",
        "book-chapter",
        "book-review",
        "conference-abstract",
        "conference-paper",
        "data-paper",
        "dataset",
        "dissertation",
        "editorial",
        "erratum",
        "letter",
        "libguides",
        "other",
        "paratext",
        "peer-review",
        "preprint",
        "reference-entry",
        "report",
        "retraction",
        "review",
        "software",
        "software-paper",
        "standard",
        "supplementary-materials",
    }
)

OPENALEX_ID_RE = re.compile(r"^I\d+$")
AUTHOR_ID_RE = re.compile(r"^A\d+$")


@dataclass(frozen=True)
class IdentitySettings:
    institution_id: str = "I27357992"
    institution_name: str = "大连理工大学"
    include_past_affiliations: bool = True
    max_author_works_count: int = 3000
    auto_resolve_single_candidate: bool = True
    max_candidates: int = 20


@dataclass(frozen=True)
class QuerySettings:
    from_date: date = date(2021, 1, 1)
    to_date: date | None = None
    work_types: tuple[str, ...] = ("article", "review", "conference-paper")
    include_retracted_in_total: bool = True
    max_works: int = 5000


@dataclass(frozen=True)
class OpenAlexSettings:
    base_url: str = "https://api.openalex.org"
    api_key_env: str = "OPENALEX_API_KEY"
    timeout_seconds: float = 30.0
    max_retries: int = 5
    backoff_base_seconds: float = 1.0
    request_interval_ms: int = 100
    per_page: int = 100
    mailto: str = ""


@dataclass(frozen=True)
class WebSearchSettings:
    enabled: bool = False
    provider: str = "none"
    max_results_per_person: int = 20
    domains: tuple[str, ...] = (
        "cnki.net",
        "wanfangdata.com.cn",
        "cqvip.com",
        "napstic.cn",
        "cjournal.hep.com.cn",
        "sciengine.com",
    )


@dataclass(frozen=True)
class OutputSettings:
    root: Path = PROJECT_ROOT / "outputs" / "scholars"


@dataclass(frozen=True)
class ScholarsConfig:
    identity: IdentitySettings = IdentitySettings()
    query: QuerySettings = QuerySettings()
    openalex: OpenAlexSettings = OpenAlexSettings()
    web_search: WebSearchSettings = WebSearchSettings()
    output: OutputSettings = OutputSettings()
    config_path: Path | None = None
    api_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": {
                "institution_id": self.identity.institution_id,
                "institution_name": self.identity.institution_name,
                "include_past_affiliations": self.identity.include_past_affiliations,
                "max_author_works_count": self.identity.max_author_works_count,
                "auto_resolve_single_candidate": self.identity.auto_resolve_single_candidate,
                "max_candidates": self.identity.max_candidates,
            },
            "query": {
                "from_date": self.query.from_date.isoformat(),
                "to_date": self.query.to_date.isoformat() if self.query.to_date else "",
                "work_types": list(self.query.work_types),
                "include_retracted_in_total": self.query.include_retracted_in_total,
                "max_works": self.query.max_works,
            },
            "openalex": {
                "base_url": self.openalex.base_url,
                "timeout_seconds": self.openalex.timeout_seconds,
                "max_retries": self.openalex.max_retries,
                "per_page": self.openalex.per_page,
                "mailto": self.openalex.mailto,
            },
            "web_search": {
                "enabled": self.web_search.enabled,
                "provider": self.web_search.provider,
                "max_results_per_person": self.web_search.max_results_per_person,
                "domains": list(self.web_search.domains),
            },
            "output": {"root": str(self.output.root)},
            "config_path": str(self.config_path) if self.config_path else "",
        }


def normalize_institution_id(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if text.startswith("https://openalex.org/"):
        text = text.rsplit("/", 1)[-1]
    if not OPENALEX_ID_RE.match(text):
        raise ConfigError(f"单位 OpenAlex ID 非法：{value!r}（应形如 I27357992）")
    return text


def normalize_author_id(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if text.startswith("https://openalex.org/"):
        text = text.rsplit("/", 1)[-1]
    if not AUTHOR_ID_RE.match(text):
        raise ConfigError(f"作者 OpenAlex ID 非法：{value!r}（应形如 A1234567890）")
    return text


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] 必须是表（table）")
    return value


def _date(value: Any, field_name: str, *, allow_empty: bool = False) -> date | None:
    if value in (None, ""):
        if allow_empty:
            return None
        raise ConfigError(f"{field_name} 不能为空")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ConfigError(f"{field_name} 不是 ISO 日期：{value!r}") from exc


def _int(value: Any, field_name: str, *, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field_name} 必须是整数：{value!r}") from exc
    if not minimum <= number <= maximum:
        raise ConfigError(f"{field_name} 必须在 {minimum}-{maximum} 之间：{number}")
    return number


def _bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{field_name} 必须是 true/false：{value!r}")


def _str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{field_name} 必须是字符串：{value!r}")
    return value


def _parse_work_types(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError("query.work_types 必须是非空字符串列表")
    types: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ConfigError(f"query.work_types 含非字符串：{item!r}")
        work_type = item.strip()
        if work_type not in VALID_WORK_TYPES:
            raise ConfigError(
                f"未知作品类型 {work_type!r}；可选：{', '.join(sorted(VALID_WORK_TYPES))}"
            )
        if work_type not in types:
            types.append(work_type)
    return tuple(types)


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def load_config(
    path: str | Path | None = None,
    *,
    overrides: dict[str, Any] | None = None,
) -> ScholarsConfig:
    """加载配置。

    ``path`` 为空时依次尝试：环境变量 ``HYDROLITAGENT_SCHOLARS_CONFIG``、
    仓库默认 ``configs/scholars.toml``、内置默认值。
    """
    config_path: Path | None = None
    requested = path or os.environ.get("HYDROLITAGENT_SCHOLARS_CONFIG")
    if requested:
        config_path = Path(requested).expanduser()
        if not config_path.is_absolute():
            config_path = (PROJECT_ROOT / config_path).resolve()
        if not config_path.is_file():
            raise ConfigError(f"配置文件不存在：{config_path}")
    elif DEFAULT_CONFIG_PATH.is_file():
        config_path = DEFAULT_CONFIG_PATH

    raw: dict[str, Any] = {}
    if config_path is not None:
        try:
            raw = load_toml(config_path)
        except Exception as exc:  # noqa: BLE001 - 统一转成 ConfigError
            raise ConfigError(f"读取配置失败：{config_path}：{exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError(f"配置根节点必须是表：{config_path}")

    identity_raw = _section(raw, "identity")
    query_raw = _section(raw, "query")
    openalex_raw = _section(raw, "openalex")
    if "api_key" in openalex_raw:
        raise ConfigError("不要在 TOML 里写 api_key；请放到环境变量 OPENALEX_API_KEY")
    web_raw = _section(raw, "web_search")
    output_raw = _section(raw, "output")
    overrides = overrides or {}

    institution_id = normalize_institution_id(
        str(overrides.get("institution_id", identity_raw.get("institution_id", "I27357992")))
    )
    from_date = _date(
        overrides.get("from_date", query_raw.get("from_date", "2021-01-01")),
        "query.from_date",
    )
    assert from_date is not None
    to_date = _date(
        overrides.get("to_date", query_raw.get("to_date", "")),
        "query.to_date",
        allow_empty=True,
    )
    if to_date is not None and to_date < from_date:
        raise ConfigError("query.to_date 不能早于 query.from_date")

    work_types_value = overrides.get("work_types", query_raw.get("work_types"))
    work_types = _parse_work_types(
        work_types_value
        if work_types_value is not None
        else ["article", "review", "conference-paper"]
    )

    identity = IdentitySettings(
        institution_id=institution_id,
        institution_name=str(identity_raw.get("institution_name", "大连理工大学")),
        include_past_affiliations=_bool(
            identity_raw.get("include_past_affiliations", True),
            "identity.include_past_affiliations",
        ),
        max_author_works_count=_int(
            identity_raw.get("max_author_works_count", 3000),
            "identity.max_author_works_count",
            minimum=1,
            maximum=10_000_000,
        ),
        auto_resolve_single_candidate=_bool(
            identity_raw.get("auto_resolve_single_candidate", True),
            "identity.auto_resolve_single_candidate",
        ),
        max_candidates=_int(
            identity_raw.get("max_candidates", 20),
            "identity.max_candidates",
            minimum=1,
            maximum=100,
        ),
    )

    query = QuerySettings(
        from_date=from_date,
        to_date=to_date,
        work_types=work_types,
        include_retracted_in_total=_bool(
            query_raw.get("include_retracted_in_total", True),
            "query.include_retracted_in_total",
        ),
        max_works=_int(
            query_raw.get("max_works", 5000),
            "query.max_works",
            minimum=1,
            maximum=100_000,
        ),
    )

    api_key_env = _str(openalex_raw.get("api_key_env", "OPENALEX_API_KEY"), "openalex.api_key_env")
    try:
        timeout_seconds = float(openalex_raw.get("timeout_seconds", 30))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"openalex.timeout_seconds 必须是数字：{openalex_raw.get('timeout_seconds')!r}") from exc
    try:
        backoff_base_seconds = float(openalex_raw.get("backoff_base_seconds", 1.0))
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"openalex.backoff_base_seconds 必须是数字：{openalex_raw.get('backoff_base_seconds')!r}"
        ) from exc
    openalex = OpenAlexSettings(
        base_url=_str(openalex_raw.get("base_url", "https://api.openalex.org"), "openalex.base_url").rstrip("/"),
        api_key_env=api_key_env,
        timeout_seconds=timeout_seconds,
        max_retries=_int(openalex_raw.get("max_retries", 5), "openalex.max_retries", minimum=0, maximum=10),
        backoff_base_seconds=backoff_base_seconds,
        request_interval_ms=_int(
            openalex_raw.get("request_interval_ms", 100),
            "openalex.request_interval_ms",
            minimum=0,
            maximum=10_000,
        ),
        per_page=_int(openalex_raw.get("per_page", 100), "openalex.per_page", minimum=1, maximum=100),
        mailto=str(openalex_raw.get("mailto", "")),
    )

    domains_raw = web_raw.get(
        "domains",
        [
            "cnki.net",
            "wanfangdata.com.cn",
            "cqvip.com",
            "napstic.cn",
            "cjournal.hep.com.cn",
            "sciengine.com",
        ],
    )
    if not isinstance(domains_raw, list) or not domains_raw:
        raise ConfigError("web_search.domains 必须是非空字符串列表")
    domains = tuple(str(item).strip() for item in domains_raw if str(item).strip())
    if not domains:
        raise ConfigError("web_search.domains 不能为空")

    web_search = WebSearchSettings(
        enabled=_bool(web_raw.get("enabled", False), "web_search.enabled"),
        provider=_str(web_raw.get("provider", "none"), "web_search.provider"),
        max_results_per_person=_int(
            web_raw.get("max_results_per_person", 20),
            "web_search.max_results_per_person",
            minimum=1,
            maximum=100,
        ),
        domains=domains,
    )
    if web_search.provider not in {"none", "manual", "firecrawl", "deepseek"}:
        raise ConfigError("web_search.provider 只能是 none / manual / firecrawl / deepseek")

    output_root_value = overrides.get(
        "output_root",
        os.environ.get("HYDROLITAGENT_SCHOLARS_OUTPUT", output_raw.get("root", "outputs/scholars")),
    )
    output_root = _resolve_path(str(output_root_value))

    return ScholarsConfig(
        identity=identity,
        query=query,
        openalex=openalex,
        web_search=web_search,
        output=OutputSettings(root=output_root),
        config_path=config_path,
        api_key=os.environ.get(api_key_env, "").strip(),
    )


def with_api_key(config: ScholarsConfig, api_key: str) -> ScholarsConfig:
    return replace(config, api_key=api_key)
