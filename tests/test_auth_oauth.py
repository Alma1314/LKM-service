"""Tests for Github OAuth — service_oauth auth URL generation and callback logic."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.models import Base
import app.modules.auth.models  # noqa: F401
from app.modules.auth.models import OAuthState


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class TestGithubAuthUrl:
    def should_contain_github_authorize_url(self, db):
        from app.modules.auth.service_oauth import get_github_auth_url

        url = get_github_auth_url(db)
        assert "github.com/login/oauth/authorize" in url

    def should_contain_client_id(self, db):
        from app.modules.auth.service_oauth import get_github_auth_url

        url = get_github_auth_url(db)
        assert f"client_id={settings.github_client_id}" in url

    def should_contain_user_email_scope(self, db):
        from app.modules.auth.service_oauth import get_github_auth_url

        url = get_github_auth_url(db)
        assert "scope=user" in url
        assert "email" in url

    def should_contain_redirect_uri(self, db):
        from app.modules.auth.service_oauth import get_github_auth_url

        url = get_github_auth_url(db)
        assert "redirect_uri=" in url

    def should_generate_server_state_token(self, db):
        from app.modules.auth.service_oauth import get_github_auth_url

        url = get_github_auth_url(db)
        # state is now server-generated; must be non-empty
        assert "&state=" in url
        # state should not be the empty placeholder
        state_idx = url.index("&state=") + len("&state=")
        state_value = url[state_idx:]
        if "&" in state_value:
            state_value = state_value.split("&")[0]
        assert len(state_value) > 0


class TestOAuthState:
    def should_store_and_consume_state(self, db):
        from app.modules.auth.service_oauth import _generate_oauth_state, _consume_oauth_state

        state = _generate_oauth_state(db, "login")
        assert len(state) > 0

        records = db.query(OAuthState).filter(OAuthState.state == state).all()
        assert len(records) == 1
        assert not records[0].consumed

        _consume_oauth_state(db, state, "login")
        db.refresh(records[0])
        assert records[0].consumed

    def should_reject_already_consumed_state(self, db):
        from app.modules.auth.service_oauth import _generate_oauth_state, _consume_oauth_state
        from app.core.err import BizError

        state = _generate_oauth_state(db, "login")
        _consume_oauth_state(db, state, "login")

        with pytest.raises(BizError):
            _consume_oauth_state(db, state, "login")

    def should_reject_wrong_purpose(self, db):
        from app.modules.auth.service_oauth import _generate_oauth_state, _consume_oauth_state
        from app.core.err import BizError

        state = _generate_oauth_state(db, "login")
        with pytest.raises(BizError):
            _consume_oauth_state(db, state, "bind")
