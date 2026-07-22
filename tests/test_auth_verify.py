import re
import time
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.err import BizError, ErrCode
from app.db.models import Base
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

# Import auth models so tables get registered
import app.modules.auth.models  # noqa: F401


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal: sessionmaker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


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
    def should_create_verification_and_return_code_and_id(self, db):
        code, record_id = create_email_verification(db, "alice@example.com", "register")

        assert re.fullmatch(r"\d{6}", code)
        assert isinstance(record_id, int)

        record = db.query(EmailVerification).filter(EmailVerification.id == record_id).first()
        assert record is not None
        assert record.email == "alice@example.com"
        assert record.purpose == "register"
        assert record.code_hash == hash_code(code, record.purpose, contact=record.email if hasattr(record, "email") else record.phone, nonce=record.nonce)
        assert record.used is False
        assert record.failed_attempts == 0


class TestCreatePhoneVerification:
    def should_create_verification_and_return_code_and_id(self, db):
        code, record_id = create_phone_verification(db, "13800138000", "login")

        assert re.fullmatch(r"\d{6}", code)
        assert isinstance(record_id, int)

        record = db.query(PhoneVerification).filter(PhoneVerification.id == record_id).first()
        assert record is not None
        assert record.phone == "13800138000"
        assert record.purpose == "login"
        assert record.code_hash == hash_code(code, record.purpose, contact=record.email if hasattr(record, "email") else record.phone, nonce=record.nonce)
        assert record.used is False
        assert record.failed_attempts == 0


class TestConsumeEmailCode:
    def should_consume_correct_code(self, db):
        code, record_id = create_email_verification(db, "alice@example.com", "register")
        result = consume_email_code(db, "alice@example.com", code, "register")
        assert result is True

        record = db.query(EmailVerification).filter(EmailVerification.id == record_id).first()
        assert record.used is True

    def should_reject_wrong_purpose(self, db):
        code, _ = create_email_verification(db, "alice@example.com", "register")

        with pytest.raises(BizError) as exc:
            consume_email_code(db, "alice@example.com", code, "login")
        assert exc.value.errcode == ErrCode.VERIFICATION_CODE_INVALID

    def should_reject_wrong_code(self, db):
        create_email_verification(db, "alice@example.com", "register")

        with pytest.raises(BizError) as exc:
            consume_email_code(db, "alice@example.com", "000000", "register")
        assert exc.value.errcode == ErrCode.VERIFICATION_CODE_INVALID

    def should_invalidate_after_three_failed_attempts(self, db):
        code, _ = create_email_verification(db, "alice@example.com", "register")

        for _ in range(3):
            with pytest.raises(BizError) as exc:
                consume_email_code(db, "alice@example.com", "000001", "register")
            assert exc.value.errcode == ErrCode.VERIFICATION_CODE_INVALID

        # The original code should be invalid now
        with pytest.raises(BizError) as exc:
            consume_email_code(db, "alice@example.com", code, "register")
        assert exc.value.errcode == ErrCode.VERIFICATION_CODE_INVALID

    def should_not_consume_expired_code(self, db):
        with patch("app.modules.auth.service_verify._now") as mock_now:
            mock_now.return_value = "2026-01-01T00:00:00+00:00"
            code, _ = create_email_verification(db, "alice@example.com", "register")

        with patch("app.modules.auth.service_verify._now") as mock_now:
            mock_now.return_value = "2026-01-02T00:00:00+00:00"
            with pytest.raises(BizError) as exc:
                consume_email_code(db, "alice@example.com", code, "register")
            assert exc.value.errcode == ErrCode.VERIFICATION_CODE_EXPIRED


class TestConsumePhoneCode:
    def should_consume_correct_code(self, db):
        code, record_id = create_phone_verification(db, "13800138000", "login")
        result = consume_phone_code(db, "13800138000", code, "login")
        assert result is True

        record = db.query(PhoneVerification).filter(PhoneVerification.id == record_id).first()
        assert record.used is True

    def should_reject_wrong_purpose(self, db):
        code, _ = create_phone_verification(db, "13800138000", "login")

        with pytest.raises(BizError) as exc:
            consume_phone_code(db, "13800138000", code, "register")
        assert exc.value.errcode == ErrCode.VERIFICATION_CODE_INVALID

    def should_reject_wrong_code(self, db):
        create_phone_verification(db, "13800138000", "login")

        with pytest.raises(BizError) as exc:
            consume_phone_code(db, "13800138000", "000000", "login")
        assert exc.value.errcode == ErrCode.VERIFICATION_CODE_INVALID

    def should_invalidate_after_three_failed_attempts(self, db):
        code, _ = create_phone_verification(db, "13800138000", "login")

        for _ in range(3):
            with pytest.raises(BizError) as exc:
                consume_phone_code(db, "13800138000", "000001", "login")
            assert exc.value.errcode == ErrCode.VERIFICATION_CODE_INVALID

        with pytest.raises(BizError) as exc:
            consume_phone_code(db, "13800138000", code, "login")
        assert exc.value.errcode == ErrCode.VERIFICATION_CODE_INVALID

    def should_not_consume_expired_code(self, db):
        with patch("app.modules.auth.service_verify._now") as mock_now:
            mock_now.return_value = "2026-01-01T00:00:00+00:00"
            code, _ = create_phone_verification(db, "13800138000", "login")

        with patch("app.modules.auth.service_verify._now") as mock_now:
            mock_now.return_value = "2026-01-02T00:00:00+00:00"
            with pytest.raises(BizError) as exc:
                consume_phone_code(db, "13800138000", code, "login")
            assert exc.value.errcode == ErrCode.VERIFICATION_CODE_EXPIRED


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
        assert exc.value.errcode == ErrCode.VERIFICATION_CODE_RATE_LIMIT

    def should_allow_after_window_expiry(self):
        key = "window@example.com"
        for _ in range(5):
            check_code_rate_limit(key, max_count=5, window=0.1)

        with pytest.raises(BizError) as exc:
            check_code_rate_limit(key, max_count=5, window=0.1)
        assert exc.value.errcode == ErrCode.VERIFICATION_CODE_RATE_LIMIT

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
        assert exc.value.errcode == ErrCode.VERIFICATION_CODE_RATE_LIMIT

        check_code_rate_limit(key_b, max_count=5, window=3600)
        # Should not raise
