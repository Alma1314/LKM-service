import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.err import BizError, ErrCode
from app.db.models import Base
import app.modules.auth.models  # noqa: F401 ensure auth tables registered
from app.modules.auth.schemas import ProfileUpdate, UserLoginInfo, UserRegInfo
from app.modules.auth.service import get_profile, login, register, update_profile


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

def _reg(db, username="alice", email="alice@example.com", password="secret123456"):
    return register(db, UserRegInfo(username=username, email=email, password=password)) # type: ignore[arg-type]


def _login(db, username="alice", password="secret123456"):
    return login(db, UserLoginInfo(username=username, password=password))


class TestRegister:
    def should_register_user(self, db):
        from app.db.models import User

        user_id = _reg(db)
        assert user_id == 1

        user = db.query(User).filter(User.id == user_id).first()
        assert user.username == "alice"
        assert user.email == "alice@example.com"
        assert "$" in user.hashed_password

    def should_reject_duplicate_username(self, db):
        _reg(db)

        with pytest.raises(BizError) as exc:
            _reg(db, email="other@example.com")

        assert exc.value.errcode == ErrCode.ALREADY_REGISTERED

    def should_reject_duplicate_email(self, db):
        _reg(db)

        with pytest.raises(BizError) as exc:
            _reg(db, username="bob")

        assert exc.value.errcode == ErrCode.ALREADY_REGISTERED


class TestLogin:
    def should_login_successfully(self, db):
        _reg(db)

        user_id = _login(db)
        assert user_id == 1

    def should_reject_nonexistent_user(self, db):
        with pytest.raises(BizError) as exc:
            _login(db)

        assert exc.value.errcode == ErrCode.INVALID_CREDENTIALS

    def should_reject_wrong_password(self, db):
        _reg(db)

        with pytest.raises(BizError) as exc:
            _login(db, password="wrongpass")

        assert exc.value.errcode == ErrCode.INVALID_CREDENTIALS


class TestProfile:
    def should_auto_create_profile_on_register(self, db):
        user_id = _reg(db)

        profile = get_profile(db, user_id)
        assert profile.nickname is None
        assert profile.avatar is None
        assert profile.role == "member"

    def should_get_profile(self, db):
        user_id = _reg(db)
        update_profile(db, user_id, ProfileUpdate(nickname="Alice"))

        profile = get_profile(db, user_id)
        assert profile.nickname == "Alice"

    def should_update_profile_partially(self, db):
        user_id = _reg(db)
        update_profile(db, user_id, ProfileUpdate(nickname="Alice"))

        update_profile(db, user_id, ProfileUpdate(avatar="/avatars/1.png"))
        profile = get_profile(db, user_id)
        assert profile.nickname == "Alice"
        assert profile.avatar == "/avatars/1.png"

    def should_reject_get_nonexistent_profile(self, db):
        with pytest.raises(BizError) as exc:
            get_profile(db, 999)
        assert exc.value.errcode == ErrCode.USER_NOT_FOUND