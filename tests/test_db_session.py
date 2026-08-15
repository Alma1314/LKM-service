"""db/session.py 的 IntegrityError 映射单测：唯一约束 vs 外键/NOT NULL。"""

import sqlite3

from sqlalchemy.exc import IntegrityError

from app.db.session import _is_unique_violation


def _ie(orig: Exception | None) -> IntegrityError:
    return IntegrityError("stmt", {}, orig)


class TestIsUniqueViolation:
    def should_detect_sqlite_unique_constraint(self):
        orig = sqlite3.IntegrityError("UNIQUE constraint failed: users.email")
        assert _is_unique_violation(_ie(orig)) is True

    def should_not_detect_sqlite_foreign_key(self):
        orig = sqlite3.IntegrityError("FOREIGN KEY constraint failed")
        assert _is_unique_violation(_ie(orig)) is False

    def should_not_detect_sqlite_not_null(self):
        orig = sqlite3.IntegrityError("NOT NULL constraint failed: users.username")
        assert _is_unique_violation(_ie(orig)) is False

    def should_detect_unique_violation_by_class_name(self):
        class UniqueViolationError(Exception):
            pass

        assert _is_unique_violation(_ie(UniqueViolationError("dup"))) is True

    def should_return_false_when_no_orig(self):
        assert _is_unique_violation(_ie(None)) is False
