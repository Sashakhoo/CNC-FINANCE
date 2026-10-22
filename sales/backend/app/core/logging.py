import json
import logging
import re
import sys
from datetime import datetime, timezone

_SECRET_KEYS = re.compile(r"(password|secret|token|api[_-]?key|authorization|cookie)", re.I)
_CONTEXT_FIELDS = ("job_id", "provider", "company_id", "contact_id", "operation", "duration_ms", "status", "error_type", "user")


def redact(value):
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _SECRET_KEYS.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for f in _CONTEXT_FIELDS:
            if hasattr(record, f):
                out[f] = getattr(record, f)
        extra = getattr(record, "data", None)
        if extra:
            out["data"] = redact(extra)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
