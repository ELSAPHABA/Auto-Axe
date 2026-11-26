"""Migrations require an explicit fixture migration connection."""

from alembic import context
from sqlalchemy.engine import Connection

connection = context.config.attributes.get("connection")
if not isinstance(connection, Connection):
    raise RuntimeError("use the fixture bootstrap with an explicit migration connection")

context.configure(connection=connection, version_table_schema="ops", transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
