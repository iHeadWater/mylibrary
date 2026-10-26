"""稳定的错误码与异常类型。

CLI 的 JSON envelope 直接使用 ``code``，因此错误码一旦发布不要随意改名。
"""

from __future__ import annotations


class ScholarsError(RuntimeError):
    code = "SCHOLARS_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class ConfigError(ScholarsError):
    code = "CONFIG_ERROR"


class RosterError(ScholarsError):
    code = "ROSTER_ERROR"


class OpenAlexError(ScholarsError):
    code = "OPENALEX_ERROR"


class OpenAlexAuthError(OpenAlexError):
    code = "OPENALEX_AUTH_ERROR"


class OpenAlexBudgetError(OpenAlexError):
    code = "OPENALEX_BUDGET_EXHAUSTED"


class IdentityError(ScholarsError):
    code = "IDENTITY_ERROR"


class OutputError(ScholarsError):
    code = "OUTPUT_ERROR"
