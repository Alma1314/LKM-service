import datetime as dt
import re
import time
from typing import Any, TypeVar, cast
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.err import BizError
from app.modules.auth.errors import AuthErr
import app.modules.auth.models  # pyright: ignore[reportUnusedImport] ensure auth tables registered
from app.modules.auth.models import EmailVerification, PhoneVerification
from app.modules.auth.service_verify import (
    check_code_rate_limit,
    consume_email_code,
    consume_phone_code,
    create_email_verification,
    create_phone_verification,
    generate_code,
    hash_code,
)

_T = TypeVar("_T")


async def _get(db: AsyncSession, model: type[_T], *where: Any) -> _T:
    # 测试均为“先建后查”，必然命中，返回类型直接按 _T 处理
    return cast(_T, (await db.execute(select(model).where(*where))).scalars().first())


class TestGenerateCode:
    def should_generate_six_digit_code(self):
        code = generate_code()
        assert re.fullmatch(r"\d{6}", code)

    def should_generate_different_codes(self):
        codes = {generate_code() for _ in range(100)}
        assert len(codes) > 1


class TestHashCode:
    def should_be_hmac_hex_string(self):
        raw = "123456"
        hashed = hash_code(raw, "register", contact="test@x.com", nonce="abc123")
        assert len(hashed) == 64  # HMAC-SHA256 => 64 hex chars

    def should_be_deterministic(self):
        assert (
            hash_code("000000", "register", contact="a@b.com", nonce="n1")
            == hash_code("000000", "register", contact="a@b.com", nonce="n1")
        )

    def should_differ_for_different_inputs(self):
        assert (
            hash_code("000000", "login", contact="a@b.com", nonce="n1")
            != hash_code("000001", "login", contact="a@b.com", nonce="n1")
        )

    def should_differ_for_different_purposes(self):
        assert (
            hash_code("123456", "login", contact="a@b.com", nonce="n1")
            != hash_code("123456", "register", contact="a@b.com", nonce="n1")
        )

    def should_differ_for_different_nonces(self):
        assert (
            hash_code("123456", "login", contact="a@b.com", nonce="n1")
            != hash_code("123456", "login", contact="a@b.com", nonce="n2")
        )


class TestCreateEmailVerification:
    async def should_create_verification_and_return_code_and_id(self, db: AsyncSession):
        code, record_id = await create_email_verification(db, "alice@example.com", "register")

        assert re.fullmatch(r"\d{6}", code)
        assert isinstance(record_id, int)

        record = await _get(db, EmailVerification, EmailVerification.id == record_id)
        assert record is not None
        assert record.email == "alice@example.com"
        assert record.purpose == "register"
        assert record.code_hash == hash_code(code, record.purpose, contact=cast(Any, record).email if hasattr(record, "email") else cast(Any, record).phone, nonce=record.nonce)
        assert record.used is False
        assert record.failed_attempts == 0


class TestCreatePhoneVerification:
    async def should_create_verification_and_return_code_and_id(self, db: AsyncSession):
        code, record_id = await create_phone_verification(db, "13800138000", "login")

        assert re.fullmatch(r"\d{6}", code)
        assert isinstance(record_id, int)

        record = await _get(db, PhoneVerification, PhoneVerification.id == record_id)
        assert record is not None
        assert record.phone == "13800138000"
        assert record.purpose == "login"
        assert record.code_hash == hash_code(code, record.purpose, contact=cast(Any, record).email if hasattr(record, "email") else cast(Any, record).phone, nonce=record.nonce)
        assert record.used is False
        assert record.failed_attempts == 0


class TestConsumeEmailCode:
    async def should_consume_correct_code(self, db: AsyncSession):
        code, record_id = await create_email_verification(db, "alice@example.com", "register")
        result = await consume_email_code(db, "alice@example.com", code, "register")
        assert result is True

        record = await _get(db, EmailVerification, EmailVerification.id == record_id)
        assert record.used is True

    async def should_reject_wrong_purpose(self, db: AsyncSession):
        code, _ = await create_email_verification(db, "alice@example.com", "register")

        with pytest.raises(BizError) as exc:
            await consume_email_code(db, "alice@example.com", code, "login")
        assert exc.value.errcode == AuthErr.VERIFICATION_CODE_INVALID

    async def should_reject_wrong_code(self, db: AsyncSession):
        await create_email_verification(db, "alice@example.com", "register")

        with pytest.raises(BizError) as exc:
            await consume_email_code(db, "alice@example.com", "000000", "register")
        assert exc.value.errcode == AuthErr.VERIFICATION_CODE_INVALID

    async def should_invalidate_after_three_failed_attempts(self, db: AsyncSession):
        code, _ = await create_email_verification(db, "alice@example.com", "register")

        for _ in range(3):
            with pytest.raises(BizError) as exc:
                await consume_email_code(db, "alice@example.com", "000001", "register")
            assert exc.value.errcode == AuthErr.VERIFICATION_CODE_INVALID

        # The original code should be invalid now
        with pytest.raises(BizError) as exc:
            await consume_email_code(db, "alice@example.com", code, "register")
        assert exc.value.errcode == AuthErr.VERIFICATION_CODE_INVALID

    async def should_not_consume_expired_code(self, db: AsyncSession):
        with patch("app.modules.auth.service_verify.now_iso") as mock_now:
            mock_now.return_value = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
            code, _ = await create_email_verification(db, "alice@example.com", "register")

        with patch("app.modules.auth.service_verify.now_iso") as mock_now:
            mock_now.return_value = dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)
            with pytest.raises(BizError) as exc:
                await consume_email_code(db, "alice@example.com", code, "register")
            assert exc.value.errcode == AuthErr.VERIFICATION_CODE_EXPIRED


class TestConsumePhoneCode:
    async def should_consume_correct_code(self, db: AsyncSession):
        code, record_id = await create_phone_verification(db, "13800138000", "login")
        result = await consume_phone_code(db, "13800138000", code, "login")
        assert result is True

        record = await _get(db, PhoneVerification, PhoneVerification.id == record_id)
        assert record.used is True

    async def should_reject_wrong_purpose(self, db: AsyncSession):
        code, _ = await create_phone_verification(db, "13800138000", "login")

        with pytest.raises(BizError) as exc:
            await consume_phone_code(db, "13800138000", code, "register")
        assert exc.value.errcode == AuthErr.VERIFICATION_CODE_INVALID

    async def should_reject_wrong_code(self, db: AsyncSession):
        await create_phone_verification(db, "13800138000", "login")

        with pytest.raises(BizError) as exc:
            await consume_phone_code(db, "13800138000", "000000", "login")
        assert exc.value.errcode == AuthErr.VERIFICATION_CODE_INVALID

    async def should_invalidate_after_three_failed_attempts(self, db: AsyncSession):
        code, _ = await create_phone_verification(db, "13800138000", "login")

        for _ in range(3):
            with pytest.raises(BizError) as exc:
                await consume_phone_code(db, "13800138000", "000001", "login")
            assert exc.value.errcode == AuthErr.VERIFICATION_CODE_INVALID

        with pytest.raises(BizError) as exc:
            await consume_phone_code(db, "13800138000", code, "login")
        assert exc.value.errcode == AuthErr.VERIFICATION_CODE_INVALID

    async def should_not_consume_expired_code(self, db: AsyncSession):
        with patch("app.modules.auth.service_verify.now_iso") as mock_now:
            mock_now.return_value = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
            code, _ = await create_phone_verification(db, "13800138000", "login")

        with patch("app.modules.auth.service_verify.now_iso") as mock_now:
            mock_now.return_value = dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)
            with pytest.raises(BizError) as exc:
                await consume_phone_code(db, "13800138000", code, "login")
            assert exc.value.errcode == AuthErr.VERIFICATION_CODE_EXPIRED


class TestCheckCodeRateLimit:
    def should_allow_within_limit(self):
        check_code_rate_limit("test@example.com", max_count=5, window=3600)
        # Should not raise

    def should_raise_when_exceeded(self):
        key = "ratelimit@example.com"
        for _ in range(5):
            check_code_rate_limit(key, max_count=5, window=3600)

        with pytest.raises(BizError) as exc:
            check_code_rate_limit(key, max_count=5, window=3600)
        assert exc.value.errcode == AuthErr.VERIFICATION_CODE_RATE_LIMIT

    def should_allow_after_window_expiry(self):
        key = "window@example.com"
        for _ in range(5):
            check_code_rate_limit(key, max_count=5, window=0.1)

        with pytest.raises(BizError) as exc:
            check_code_rate_limit(key, max_count=5, window=0.1)
        assert exc.value.errcode == AuthErr.VERIFICATION_CODE_RATE_LIMIT

        time.sleep(0.15)
        check_code_rate_limit(key, max_count=5, window=0.1)
        # Should not raise

    def should_isolate_different_keys(self):
        key_a = "key_a@example.com"
        key_b = "key_b@example.com"

        for _ in range(5):
            check_code_rate_limit(key_a, max_count=5, window=3600)

        with pytest.raises(BizError) as exc:
            check_code_rate_limit(key_a, max_count=5, window=3600)
        assert exc.value.errcode == AuthErr.VERIFICATION_CODE_RATE_LIMIT

        check_code_rate_limit(key_b, max_count=5, window=3600)
        # Should not raise
