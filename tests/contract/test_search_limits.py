"""Ограничение поиска по длине (ТЗ п.94)."""
from apps.core.filters import MIN_SEARCH_LENGTH

from .base import ContractTestCase
from .factories import make_admin, make_student, make_university


class SearchLengthTest(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.uni = make_university()
        # Имена подобраны так, чтобы короткий запрос "Zz" совпадал ровно
        # с одним студентом: иначе тест прошёл бы и без фильтра, по совпадению.
        make_student(self.uni, student_id="S-0001", full_name="Zzyzx Уникум")
        make_student(self.uni, student_id="S-0002", full_name="Бекова Айпери")
        make_student(self.uni, student_id="S-0003", full_name="Иванов Иван")
        self.admin = make_admin(email="super@test.kg")
        self.as_admin(self.admin)

    def _search(self, term):
        return self.client.get(f"/api/v1/admin/students/?search={term}")

    def test_long_enough_search_filters(self):
        res = self._search("Zzy")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 1)

    def test_one_character_search_is_ignored(self):
        """Пользователь набирает по символу — ошибка на каждом первом хуже,
        чем отсутствие фильтрации."""
        res = self._search("Z")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 3, "короткий запрос не должен фильтровать")

    def test_two_character_search_is_ignored(self):
        res = self._search("Zz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            len(res.data["results"]), 3,
            "двухсимвольный запрос совпал бы ровно с одним студентом — "
            "значит фильтр по длине не сработал",
        )

    def test_minimum_length_is_three(self):
        self.assertEqual(MIN_SEARCH_LENGTH, 3)

    def test_search_still_works_across_fields(self):
        res = self._search("S-0002")
        self.assertEqual(len(res.data["results"]), 1)
        self.assertEqual(res.data["results"][0]["student_id"], "S-0002")
