"""Структурные границы слоёв (ТЗ п.104).

ТЗ запрещает писать логику блокировок и кэширования прямо во view.
Проверка структурная, а не поведенческая: нарушение этой границы не ломает
ни один тест — оно просто делает код невозможным для рассуждения и
разводит две копии одной политики.

Это уже происходило: чтение кэша статуса голосования жило во view, запись —
в сервисе, и они разошлись. `voted_at` приходил пустым ровно при попадании
в кэш — дефект, который не поймал ни один тест того времени.
"""
import pathlib

from django.test import SimpleTestCase

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
VIEW_FILES = sorted(REPO_ROOT.glob("apps/*/views.py"))

# Прямая работа с кэшем и блокировками — признак логики, вытекшей из
# сервисного слоя во view.
FORBIDDEN_IN_VIEWS = (
    ("apps.core.db_locks", "логика блокировок"),
    ("advisory_lock", "логика блокировок"),
    ("safe_get", "работа с кэшем напрямую"),
    ("safe_set", "работа с кэшем напрямую"),
    ("safe_delete", "работа с кэшем напрямую"),
)


class ViewsStayThinTest(SimpleTestCase):
    def test_views_contain_no_locking_or_caching_logic(self):
        offenders = []
        for path in VIEW_FILES:
            source = path.read_text(encoding="utf-8")
            for token, what in FORBIDDEN_IN_VIEWS:
                if token in source:
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}: {what} ({token})"
                    )
        self.assertEqual(
            offenders,
            [],
            "Эта логика принадлежит сервисному слою, а не view (ТЗ п.104):\n  "
            + "\n  ".join(offenders),
        )

    def test_view_modules_were_actually_found(self):
        """Тест, который ничего не просканировал, ничего и не доказывает."""
        self.assertGreaterEqual(len(VIEW_FILES), 5)
