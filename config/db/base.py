"""MySQL/MariaDB backend that also works on MariaDB 10.4 (the version XAMPP ships).

Django 6.1 officially needs MariaDB 10.11+ (or MySQL 8.4+). This thin layer relaxes that for older
MariaDB by:
  * accepting MariaDB >= 10.4 in the startup version check, and
  * turning off `INSERT ... RETURNING`, which MariaDB only supports from 10.5 (Django then reads the
    new row's id from `LAST_INSERT_ID()` instead, exactly as it did before 6.0), and
  * storing UUIDs as char(32) instead of the native `uuid` type (MariaDB 10.7+), and
  * renaming columns with `CHANGE` instead of `RENAME COLUMN` (MariaDB 10.5+).

The project sticks to plain ORM features (no JSON/UUID columns, no expression indexes) and the test
suite runs against the real database, so regressions show up there. Upgrade the database to MariaDB
10.11+ or MySQL 8.4 before going to production, then set ENGINE back to
'django.db.backends.mysql' and delete this package.
"""
from django.db.backends.mysql import base, features, schema


class DatabaseFeatures(features.DatabaseFeatures):
    @property
    def can_return_columns_from_insert(self):
        return False

    @property
    def can_return_rows_from_bulk_insert(self):
        return False

    # MariaDB only has a native `uuid` column type from 10.7; older servers store UUIDs as char(32).
    @property
    def has_native_uuid_field(self):
        return False


class DatabaseSchemaEditor(schema.DatabaseSchemaEditor):
    # MariaDB < 10.5 has no `RENAME COLUMN`; `CHANGE` does the same and takes the full column definition,
    # which Django already passes in `%(type)s` (including NULL / NOT NULL).
    sql_rename_column = "ALTER TABLE %(table)s CHANGE %(old_column)s %(new_column)s %(type)s"


class DatabaseWrapper(base.DatabaseWrapper):
    features_class = DatabaseFeatures
    SchemaEditorClass = DatabaseSchemaEditor

    def check_database_version_supported(self):
        if self.mysql_is_mariadb and self.mysql_version >= (10, 4):
            return
        super().check_database_version_supported()
