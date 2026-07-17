import sqlite3

import pytest

from db import initdb
from err import BizError, ErrCode
from model import UserLoginInfo, UserRegInfo
from svc import login, register


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    initdb(c)
    return c


def _reg(conn, username="alice", email="alice@example.com", password="secret123"):
    return register(conn, UserRegInfo(username=username, email=email, password=password))


def _login(conn, username="alice", password="secret123"):
    return login(conn, UserLoginInfo(username=username, password=password))


class TestRegister:
    def should_register_user(self, conn):
        user_id = _reg(conn)
        assert user_id == 1

        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        assert row["username"] == "alice"
        assert row["email"] == "alice@example.com"
        assert "$" in row["hpwd"]

    def should_reject_duplicate_username(self, conn):
        _reg(conn)

        with pytest.raises(BizError) as exc:
            _reg(conn, email="other@example.com")

        assert exc.value.errcode == ErrCode.ALREADY_REGISTERED

    def should_reject_duplicate_email(self, conn):
        _reg(conn)

        with pytest.raises(BizError) as exc:
            _reg(conn, username="bob")

        assert exc.value.errcode == ErrCode.ALREADY_REGISTERED


class TestLogin:
    def should_login_successfully(self, conn):
        _reg(conn)

        user_id = _login(conn)
        assert user_id == 1

    def should_reject_nonexistent_user(self, conn):
        with pytest.raises(BizError) as exc:
            _login(conn)

        assert exc.value.errcode == ErrCode.USER_NOT_FOUND

    def should_reject_wrong_password(self, conn):
        _reg(conn)

        with pytest.raises(BizError) as exc:
            _login(conn, password="wrongpass")

        assert exc.value.errcode == ErrCode.INVALID_CREDENTIALS
