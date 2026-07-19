import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic import context
from app.core.config import settings
from app.db.models import Base

config = context.config
target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", settings.database_url)