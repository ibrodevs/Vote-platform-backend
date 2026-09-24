"""Операции миграций, безопасные для больших таблиц (ТЗ п.54).

ЗАЧЕМ
-----
Обычный `CREATE INDEX` берёт на таблице блокировку SHARE: чтения проходят,
а любая запись ждёт окончания построения. На таблице студентов в миллион
строк это десятки секунд, в течение которых нельзя ни импортировать список,
ни зарегистрироваться, ни проголосовать (голос пишет VoteRecord с внешним
ключом на студента).

`CREATE INDEX CONCURRENTLY` строит индекс в два прохода, не блокируя запись.
Платить приходится тем, что операция не может выполняться внутри транзакции —
отсюда `atomic = False` в миграции — и что при сбое остаётся невалидный
индекс, который нужно удалить вручную.

ПОЧЕМУ НЕ ПРОСТО AddIndexConcurrently ИЗ DJANGO
-----------------------------------------------
`django.contrib.postgres.operations.AddIndexConcurrently` падает на SQLite,
а проект сохраняет SQLite для локальной разработки (ТЗ п.12). Эта обёртка
выбирает нужный вариант по движку базы.
"""
from django.db.migrations.operations.models import AddIndex, RemoveIndex


class AddIndexSafely(AddIndex):
    """AddIndex, который на PostgreSQL строится CONCURRENTLY.

    Миграция, использующая эту операцию, ОБЯЗАНА объявить `atomic = False`:
    PostgreSQL не позволяет CREATE INDEX CONCURRENTLY внутри транзакции.
    """

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != 'postgresql':
            return super().database_forwards(app_label, schema_editor, from_state, to_state)

        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return

        index_sql = str(self.index.create_sql(model, schema_editor, concurrently=True))
        schema_editor.execute(index_sql, params=None)


class RemoveIndexSafely(RemoveIndex):
    """RemoveIndex, который на PostgreSQL удаляет CONCURRENTLY."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != 'postgresql':
            return super().database_forwards(app_label, schema_editor, from_state, to_state)

        model = from_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return

        from_model_state = from_state.models[app_label, self.model_name_lower]
        index = from_model_state.get_index_by_name(self.name)
        schema_editor.execute(index.remove_sql(model, schema_editor, concurrently=True))
