"""Логирование с маскированием телефонов."""
import logging
import re

# +7 777 123 45 67, 87771234567, 7771234567 и т.п.
_PHONE_RE = re.compile(r"(?<!\d)(\+?[78])?[\s\-\(]*(\d{3})[\s\-\)]*(\d{3})[\s\-]*(\d{2})[\s\-]*(\d{2})(?!\d)")


def mask_phones(text: str) -> str:
    return _PHONE_RE.sub(lambda m: f"***{m.group(5)}", text)


class PhoneMaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        masked = mask_phones(msg)
        if masked != msg:
            record.msg = masked
            record.args = ()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(PhoneMaskFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
