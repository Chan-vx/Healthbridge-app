"""
Brings an existing database up to the current schema.

create_all() creates missing tables but never adds columns to existing ones, so a
database created before a column was added (e.g. the Docker volume) is patched here.
"""

import logging

from sqlalchemy import Engine, inspect, text

from app.database import Base

log = logging.getLogger("healthbridge")

# Values for rows that existed before the authenticity checks
BACKFILL = [
    "UPDATE bills SET verification_status = CASE "
    "WHEN uploaded_by IN (SELECT id FROM users WHERE role = 'hospital') THEN 'hospital_uploaded' "
    "WHEN hospital_id IS NULL THEN 'unverifiable' ELSE 'pending' END "
    "WHERE verification_status IS NULL",
    "UPDATE bills SET checks = '[]' WHERE checks IS NULL",
]


def add_missing_columns(engine: Engine) -> list[str]:
    existing = inspect(engine)
    added = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not existing.has_table(table.name):
                continue
            present = {c["name"] for c in existing.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                ddl = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {column.name} {ddl}'))
                added.append(f"{table.name}.{column.name}")
        for statement in BACKFILL:
            conn.execute(text(statement))
    for name in added:
        log.warning("Added column %s to the existing database", name)
    return added
