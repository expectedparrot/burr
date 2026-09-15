"""Diagnostics shared by the parser, evaluator, and CLI."""

from dataclasses import asdict, dataclass, field


@dataclass
class Diagnostic:
    code: str
    message: str
    where: dict = field(default_factory=dict)
    fix_hint: str = "correct the referenced value or expression"
    severity: str = "error"

    def to_dict(self):
        return asdict(self)


class BurrError(Exception):
    def __init__(self, code, message, *, file="", key="", hint=None, exit_code=1):
        self.diagnostics = [Diagnostic(code, message, {"file": str(file), "key": str(key)},
                                       hint or "correct the referenced value or expression")]
        self.exit_code = exit_code
        super().__init__(message)

    @classmethod
    def many(cls, diagnostics):
        error = cls("eval_error", "model diagnostics")
        error.diagnostics = diagnostics
        return error


def require(condition, code, message, **kwargs):
    if not condition:
        raise BurrError(code, message, **kwargs)
