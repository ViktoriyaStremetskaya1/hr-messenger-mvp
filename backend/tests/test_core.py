import logging

import pytest

from app.core import crypto
from app.core.logging import PhoneMaskFilter, mask_phones
from app.services.phone import PhoneError, normalize_phone


@pytest.mark.parametrize(
    "raw",
    ["+7 777 123 45 67", "8 (777) 123-45-67", "87771234567", "7771234567", "77771234567", 77771234567.0, " +7-777-123-4567 "],
)
def test_normalize_phone_variants(raw):
    assert normalize_phone(raw) == "+77771234567"


@pytest.mark.parametrize("raw", [None, "", "123", "+7 495 123 45 67", "+7 727 123 45 67", "+1 202 555 0101 22"])
def test_normalize_phone_rejects(raw):
    with pytest.raises(PhoneError):
        normalize_phone(raw)


def test_encrypt_roundtrip_and_nonce():
    a, b = crypto.encrypt("+77771234567"), crypto.encrypt("+77771234567")
    assert a != b  # случайный nonce
    assert a.startswith("v1:")
    assert crypto.decrypt(a) == "+77771234567"
    assert "7771234567" not in a


def test_phone_hash_deterministic():
    assert crypto.phone_hash("+77771234567") == crypto.phone_hash("+77771234567")
    assert crypto.phone_hash("+77771234567") != crypto.phone_hash("+77771234568")


def test_mask_phones_in_text():
    s = mask_phones("Отправка на +7 777 123 45 67 и 87011234567, заказ 12")
    assert "123 45" not in s and "8701123" not in s
    assert "***67" in s and "заказ 12" in s


def test_log_filter_masks(caplog):
    logger = logging.getLogger("t")
    logger.addFilter(PhoneMaskFilter())
    with caplog.at_level(logging.INFO):
        logger.info("phone %s", "+77771234567")
    assert "7771234567" not in caplog.text
