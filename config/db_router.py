"""Роутер баз данных: реплика доступна только для чтения (ТЗ п.46).

Роутер здесь выполняет ровно одну задачу — не дать записи и миграциям уйти
на реплику. Выбор базы для чтения он НЕ делает: почему именно так, объяснено
в `apps/core/db_replica.py`.

Запись на реплику физически невозможна (PostgreSQL standby доступен только
для чтения), поэтому ошибка проявилась бы как исключение в production.
Роутер превращает её в невозможность на уровне приложения.
"""
from apps.core.db_replica import PRIMARY_ALIAS


class PrimaryWriteRouter:
    def db_for_read(self, model, **hints):
        # None = «решение не принято»: Django возьмёт базу из самого запроса,
        # то есть primary по умолчанию или ту, что указана через .using().
        return None

    def db_for_write(self, model, **hints):
        """Любая запись — только primary. Исключений не бывает."""
        return PRIMARY_ALIAS

    def allow_relation(self, obj1, obj2, **hints):
        # Primary и реплика — одна и та же база, связи между объектами
        # из них корректны.
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """Схему меняет только primary: реплика получает её по репликации."""
        return db == PRIMARY_ALIAS
