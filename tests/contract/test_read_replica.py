"""Готовность к реплике чтения (ТЗ п.46).

Главный риск реплики — не производительность, а показанный студенту
устаревший статус голосования: увидев «вы ещё не голосовали» после
успешного голоса, человек нажмёт кнопку второй раз.

Поэтому проверяется не то, что реплика используется, а то, что она
**не используется там, где нельзя**.
"""
import pathlib

from django.test import SimpleTestCase, override_settings

from apps.core.db_replica import PRIMARY_ALIAS, REPLICA_ALIAS, eventual, read_alias, replica_configured
from apps.voting.models import VoteRecord
from config.db_router import PrimaryWriteRouter

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Модули, принимающие решения о голосовании. Ни один запрос отсюда
# не имеет права уйти на отстающую копию базы.
CRITICAL_MODULES = (
    "apps/voting/services.py",
    "apps/voting/views.py",
    "apps/elections/services.py",
    "apps/elections/views.py",
    "apps/elections/aggregates.py",
    "apps/core/authentication.py",
)


class RouterTest(SimpleTestCase):
    def setUp(self):
        self.router = PrimaryWriteRouter()

    def test_writes_always_go_to_primary(self):
        self.assertEqual(self.router.db_for_write(VoteRecord), PRIMARY_ALIAS)

    def test_router_does_not_choose_a_read_database(self):
        """Чтения роутер не выбирает: критерий — смысл запроса, а не модель.

        Одна и та же модель читается и в критичной проверке, и в отчёте.
        Роутер по модели различить их не может, поэтому решение принимается
        явной пометкой в коде.
        """
        self.assertIsNone(self.router.db_for_read(VoteRecord))

    def test_migrations_only_on_primary(self):
        self.assertTrue(self.router.allow_migrate(PRIMARY_ALIAS, "voting"))
        self.assertFalse(self.router.allow_migrate(REPLICA_ALIAS, "voting"))


class EventualHelperTest(SimpleTestCase):
    def test_without_replica_reads_go_to_primary(self):
        """Без настроенной реплики пометка ничего не меняет."""
        self.assertFalse(replica_configured())
        self.assertEqual(read_alias(), PRIMARY_ALIAS)
        self.assertEqual(eventual(VoteRecord.objects.all()).db, PRIMARY_ALIAS)

    def test_with_replica_marked_reads_go_to_replica(self):
        from django.conf import settings

        replica_config = {**settings.DATABASES[PRIMARY_ALIAS]}
        with override_settings(DATABASES={**settings.DATABASES, REPLICA_ALIAS: replica_config}):
            self.assertTrue(replica_configured())
            self.assertEqual(eventual(VoteRecord.objects.all()).db, REPLICA_ALIAS)


class CriticalPathsNeverUseReplicaTest(SimpleTestCase):
    """Структурная проверка: пометка не должна появиться в критичном коде.

    Тест поведения здесь недостаточен: без настроенной реплики `eventual()`
    читает primary, и ошибочная пометка в коде голосования была бы незаметна
    до самого production, где реплика появится.
    """

    def test_voting_and_auth_do_not_mark_reads_as_eventual(self):
        offenders = []
        for rel_path in CRITICAL_MODULES:
            path = REPO_ROOT / rel_path
            if not path.exists():
                continue
            source = path.read_text(encoding="utf-8")
            if "eventual" in source or f'using("{REPLICA_ALIAS}")' in source:
                offenders.append(rel_path)
        self.assertEqual(
            offenders,
            [],
            "Эти модули принимают решения о голосовании и обязаны читать "
            f"primary (ТЗ п.46): {offenders}",
        )
