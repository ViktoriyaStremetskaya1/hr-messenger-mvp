"""Нормализация номеров Казахстана к E.164 (+7XXXXXXXXXX)."""
import re

# Мобильные коды операторов РК: 700-708, 747, 750-751, 760-764, 771, 775-778
KZ_MOBILE_PREFIXES = (
    tuple(f"70{i}" for i in range(0, 9))
    + ("747", "750", "751", "760", "761", "762", "763", "764", "771", "775", "776", "777", "778")
)


class PhoneError(ValueError):
    pass


def normalize_phone(raw: object) -> str:
    """Возвращает номер в формате +77XXXXXXXXX или бросает PhoneError.

    Поддерживаемые варианты: +7 777 123 45 67, 8 (777) 123-45-67, 87771234567, 7771234567,
    77771234567, 7.77712345e10 (Excel превратил в число).
    """
    if raw is None:
        raise PhoneError("пустой номер")
    if isinstance(raw, float):
        raw = f"{raw:.0f}"
    s = str(raw).strip()
    if not s:
        raise PhoneError("пустой номер")
    digits = re.sub(r"\D", "", s)
    if len(digits) == 11 and digits[0] in "78":
        digits = digits[1:]
    elif len(digits) == 10:
        pass
    else:
        raise PhoneError(f"неверная длина номера ({len(digits)} цифр)")
    if not digits.startswith(KZ_MOBILE_PREFIXES):
        raise PhoneError("не мобильный номер Казахстана")
    return "+7" + digits
