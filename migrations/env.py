from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.db import Base
from app.modules.assets import models as asset_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.blank_requests import models as blank_request_models  # noqa: F401
from app.modules.daily_reports import models as daily_report_models  # noqa: F401
from app.modules.defects import models as defect_models  # noqa: F401
from app.modules.downtime import models as downtime_models  # noqa: F401
from app.modules.employees import models as employee_models  # noqa: F401
from app.modules.form_templates import models as form_template_models  # noqa: F401
from app.modules.imports import models as import_models  # noqa: F401
from app.modules.orders import models as order_models  # noqa: F401
from app.modules.products import models as product_models  # noqa: F401
from app.modules.qc import models as qc_models  # noqa: F401
from app.modules.repairs import models as repair_models  # noqa: F401
from app.modules.schedules import models as schedule_models  # noqa: F401
from app.modules.settings import models as setting_models  # noqa: F401
from app.modules.shifts import models as shift_models  # noqa: F401
from app.modules.users import models as user_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().migration_database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().migration_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
