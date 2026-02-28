"""Migration v2.6.0: Change sessions PK to composite (session_id, session_type)

Fixes issue #6733: Agent and Team sharing the same session_id overwrite each
other's session data.

Changes:
- Drop single-column PRIMARY KEY on session_id
- Add composite PRIMARY KEY on (session_id, session_type)
"""

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.utils import quote_db_identifier
from agno.utils.log import log_error, log_info

try:
    from sqlalchemy import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`")


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def up(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Migrate sessions table to composite PK (session_id, session_type).

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "sessions":
            return False

        if db_type == "PostgresDb":
            return _migrate_postgres(db, table_name)
        elif db_type == "MySQLDb":
            return _migrate_mysql(db, table_name)
        elif db_type == "SingleStoreDb":
            return _migrate_singlestore(db, table_name)
        elif db_type == "SqliteDb":
            return _migrate_sqlite(db, table_name)
        else:
            log_info(f"{db_type} does not require schema migrations")
        return False
    except Exception as e:
        log_error(f"Error running migration v2.6.0 for {db_type} on table {table_name}: {e}")
        raise


async def async_up(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Async: migrate sessions table to composite PK (session_id, session_type).

    Returns:
        bool: True if any migration was applied, False otherwise.
    """
    db_type = type(db).__name__

    try:
        if table_type != "sessions":
            return False

        if db_type == "AsyncPostgresDb":
            return await _migrate_async_postgres(db, table_name)
        elif db_type == "AsyncMySQLDb":
            return await _migrate_async_mysql(db, table_name)
        elif db_type == "AsyncSqliteDb":
            return await _migrate_async_sqlite(db, table_name)
        else:
            log_info(f"{db_type} does not require schema migrations")
        return False
    except Exception as e:
        log_error(f"Error running migration v2.6.0 for {db_type} on table {table_name}: {e}")
        raise


def down(db: BaseDb, table_type: str, table_name: str) -> bool:
    """Not implemented – this migration is forward-only."""
    return False


async def async_down(db: AsyncBaseDb, table_type: str, table_name: str) -> bool:
    """Not implemented – this migration is forward-only."""
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pk_column_count(sess, db_schema: str, table_name: str, dialect: str) -> int:
    """Return the number of columns in the current primary key."""
    if dialect == "postgres":
        result = sess.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.key_column_usage kcu "
                "JOIN information_schema.table_constraints tc "
                "ON kcu.constraint_name = tc.constraint_name "
                "AND kcu.table_schema = tc.table_schema "
                "AND kcu.table_name = tc.table_name "
                "WHERE tc.constraint_type = 'PRIMARY KEY' "
                "AND tc.table_schema = :schema AND tc.table_name = :table"
            ),
            {"schema": db_schema, "table": table_name},
        )
    else:
        # MySQL / SingleStore
        result = sess.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.key_column_usage "
                "WHERE constraint_name = 'PRIMARY' "
                "AND table_schema = :schema AND table_name = :table"
            ),
            {"schema": db_schema, "table": table_name},
        )
    return result.scalar() or 0


async def _async_pk_column_count(sess, db_schema: str, table_name: str, dialect: str) -> int:
    """Async version of _pk_column_count."""
    if dialect == "postgres":
        result = await sess.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.key_column_usage kcu "
                "JOIN information_schema.table_constraints tc "
                "ON kcu.constraint_name = tc.constraint_name "
                "AND kcu.table_schema = tc.table_schema "
                "AND kcu.table_name = tc.table_name "
                "WHERE tc.constraint_type = 'PRIMARY KEY' "
                "AND tc.table_schema = :schema AND tc.table_name = :table"
            ),
            {"schema": db_schema, "table": table_name},
        )
    else:
        result = await sess.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.key_column_usage "
                "WHERE constraint_name = 'PRIMARY' "
                "AND table_schema = :schema AND table_name = :table"
            ),
            {"schema": db_schema, "table": table_name},
        )
    return result.scalar() or 0


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


def _migrate_postgres(db: BaseDb, table_name: str) -> bool:
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"

    with db.Session() as sess, sess.begin():  # type: ignore
        # Check if table exists
        exists = sess.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :schema AND table_name = :table"
            ),
            {"schema": db_schema, "table": table_name},
        ).scalar()
        if not exists:
            return False

        # Already a composite PK?
        pk_cols = _pk_column_count(sess, db_schema, table_name, "postgres")
        if pk_cols >= 2:
            log_info(f"Composite PK already present on {full_table}, skipping migration")
            return False

        # Find current PK constraint name
        pk_name_row = sess.execute(
            text(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_schema = :schema AND table_name = :table "
                "AND constraint_type = 'PRIMARY KEY'"
            ),
            {"schema": db_schema, "table": table_name},
        ).fetchone()

        if pk_name_row:
            pk_name = quote_db_identifier(db_type, pk_name_row[0])
            sess.execute(text(f"ALTER TABLE {full_table} DROP CONSTRAINT {pk_name}"))

        sess.execute(
            text(f"ALTER TABLE {full_table} ADD PRIMARY KEY (session_id, session_type)")
        )
        log_info(f"Migrated {full_table}: PK is now (session_id, session_type)")
        return True


async def _migrate_async_postgres(db: AsyncBaseDb, table_name: str) -> bool:
    db_schema = db.db_schema or "public"  # type: ignore
    db_type = type(db).__name__
    quoted_schema = quote_db_identifier(db_type, db_schema)
    quoted_table = quote_db_identifier(db_type, table_name)
    full_table = f"{quoted_schema}.{quoted_table}"

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        exists = (
            await sess.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": db_schema, "table": table_name},
            )
        ).scalar()
        if not exists:
            return False

        pk_cols = await _async_pk_column_count(sess, db_schema, table_name, "postgres")
        if pk_cols >= 2:
            log_info(f"Composite PK already present on {full_table}, skipping migration")
            return False

        pk_name_row = (
            await sess.execute(
                text(
                    "SELECT constraint_name FROM information_schema.table_constraints "
                    "WHERE table_schema = :schema AND table_name = :table "
                    "AND constraint_type = 'PRIMARY KEY'"
                ),
                {"schema": db_schema, "table": table_name},
            )
        ).fetchone()

        if pk_name_row:
            pk_name = quote_db_identifier(db_type, pk_name_row[0])
            await sess.execute(text(f"ALTER TABLE {full_table} DROP CONSTRAINT {pk_name}"))

        await sess.execute(
            text(f"ALTER TABLE {full_table} ADD PRIMARY KEY (session_id, session_type)")
        )
        log_info(f"Migrated {full_table}: PK is now (session_id, session_type)")
        return True


# ---------------------------------------------------------------------------
# MySQL
# ---------------------------------------------------------------------------


def _migrate_mysql(db: BaseDb, table_name: str) -> bool:
    db_schema = db.db_schema  # type: ignore
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)

    with db.Session() as sess, sess.begin():  # type: ignore
        pk_cols = _pk_column_count(sess, db_schema, table_name, "mysql")
        if pk_cols >= 2:
            log_info(f"Composite PK already present on {quoted_table}, skipping migration")
            return False

        sess.execute(text(f"ALTER TABLE {quoted_table} DROP PRIMARY KEY, ADD PRIMARY KEY (session_id, session_type)"))
        log_info(f"Migrated {quoted_table}: PK is now (session_id, session_type)")
        return True


async def _migrate_async_mysql(db: AsyncBaseDb, table_name: str) -> bool:
    db_schema = db.db_schema  # type: ignore
    db_type = type(db).__name__
    quoted_table = quote_db_identifier(db_type, table_name)

    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        pk_cols = await _async_pk_column_count(sess, db_schema, table_name, "mysql")
        if pk_cols >= 2:
            log_info(f"Composite PK already present on {quoted_table}, skipping migration")
            return False

        await sess.execute(
            text(f"ALTER TABLE {quoted_table} DROP PRIMARY KEY, ADD PRIMARY KEY (session_id, session_type)")
        )
        log_info(f"Migrated {quoted_table}: PK is now (session_id, session_type)")
        return True


# ---------------------------------------------------------------------------
# SingleStore
# ---------------------------------------------------------------------------


def _migrate_singlestore(db: BaseDb, table_name: str) -> bool:
    # SingleStore uses the same SQL syntax as MySQL for PK changes
    return _migrate_mysql(db, table_name)


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------


def _migrate_sqlite(db: BaseDb, table_name: str) -> bool:
    """SQLite does not support ALTER TABLE ... DROP PRIMARY KEY, so we recreate the table."""
    with db.Session() as sess, sess.begin():  # type: ignore
        # Check current PK columns
        pk_info = sess.execute(text(f'PRAGMA table_info("{table_name}")')).fetchall()
        pk_cols = [row[1] for row in pk_info if row[5] > 0]  # col index 5 = pk flag

        if len(pk_cols) >= 2:
            log_info(f"Composite PK already present on {table_name}, skipping migration")
            return False

        # Get all column definitions
        columns = []
        for row in pk_info:
            col_name = row[1]
            col_type = row[2]
            not_null = "NOT NULL" if row[3] else ""
            default = f"DEFAULT {row[4]}" if row[4] is not None else ""
            columns.append(f'"{col_name}" {col_type} {not_null} {default}'.strip())

        columns_def = ", ".join(columns)
        tmp_table = f"{table_name}__migrate_v260"

        sess.execute(text(
            f'CREATE TABLE "{tmp_table}" ({columns_def}, PRIMARY KEY (session_id, session_type))'
        ))
        # Copy data
        col_names = ", ".join(f'"{row[1]}"' for row in pk_info)
        sess.execute(text(f'INSERT INTO "{tmp_table}" ({col_names}) SELECT {col_names} FROM "{table_name}"'))
        sess.execute(text(f'DROP TABLE "{table_name}"'))
        sess.execute(text(f'ALTER TABLE "{tmp_table}" RENAME TO "{table_name}"'))

        log_info(f"Migrated {table_name}: PK is now (session_id, session_type)")
        return True


async def _migrate_async_sqlite(db: AsyncBaseDb, table_name: str) -> bool:
    """Async SQLite migration: recreate table with composite PK."""
    async with db.async_session_factory() as sess, sess.begin():  # type: ignore
        result = await sess.execute(text(f'PRAGMA table_info("{table_name}")'))
        pk_info = result.fetchall()
        pk_cols = [row[1] for row in pk_info if row[5] > 0]

        if len(pk_cols) >= 2:
            log_info(f"Composite PK already present on {table_name}, skipping migration")
            return False

        columns = []
        for row in pk_info:
            col_name = row[1]
            col_type = row[2]
            not_null = "NOT NULL" if row[3] else ""
            default = f"DEFAULT {row[4]}" if row[4] is not None else ""
            columns.append(f'"{col_name}" {col_type} {not_null} {default}'.strip())

        columns_def = ", ".join(columns)
        tmp_table = f"{table_name}__migrate_v260"

        await sess.execute(text(
            f'CREATE TABLE "{tmp_table}" ({columns_def}, PRIMARY KEY (session_id, session_type))'
        ))
        col_names = ", ".join(f'"{row[1]}"' for row in pk_info)
        await sess.execute(text(f'INSERT INTO "{tmp_table}" ({col_names}) SELECT {col_names} FROM "{table_name}"'))
        await sess.execute(text(f'DROP TABLE "{table_name}"'))
        await sess.execute(text(f'ALTER TABLE "{tmp_table}" RENAME TO "{table_name}"'))

        log_info(f"Migrated {table_name}: PK is now (session_id, session_type)")
        return True
