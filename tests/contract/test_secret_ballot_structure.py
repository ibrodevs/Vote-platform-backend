"""Структурные тесты тайны голосования (ТЗ п.71).

Проверки идут не по списку известных имён полей, а обходом ВСЕХ моделей
и сериализаторов проекта. Так тест поймает связь Student <-> Candidate,
появившуюся где угодно, а не только в двух ожидаемых местах.
"""
import importlib
import pkgutil

from django.apps import apps
from django.test import TestCase
from rest_framework import serializers

from apps.candidates.models import Candidate
from apps.students.models import Student
from apps.voting.models import Ballot, VoteRecord

from .base import ContractTestCase
from .factories import make_candidate, make_election, make_student, make_university


def _related_models(model):
    """Все модели, на которые ссылается данная — напрямую через FK/O2O/M2M."""
    found = set()
    for field in model._meta.get_fields():
        if getattr(field, "related_model", None) is not None and field.concrete:
            found.add(field.related_model)
    return found


class BallotIsolationTest(TestCase):
    def test_ballot_has_no_student_relation(self):
        self.assertNotIn(Student, _related_models(Ballot))

    def test_ballot_has_no_vote_record_relation(self):
        self.assertNotIn(VoteRecord, _related_models(Ballot))

    def test_vote_record_has_no_candidate_relation(self):
        self.assertNotIn(Candidate, _related_models(VoteRecord))

    def test_vote_record_has_no_ballot_relation(self):
        self.assertNotIn(Ballot, _related_models(VoteRecord))

    def test_ballot_field_names_mention_no_student(self):
        names = {f.name for f in Ballot._meta.get_fields()}
        forbidden = {"student", "student_id", "voter", "vote_record", "voterecord"}
        self.assertEqual(names & forbidden, set())

    def test_vote_record_field_names_mention_no_candidate(self):
        names = {f.name for f in VoteRecord._meta.get_fields()}
        forbidden = {"candidate", "candidate_id", "choice", "ballot"}
        self.assertEqual(names & forbidden, set())


class NoModelLinksStudentAndCandidateTest(TestCase):
    """Самая широкая проверка: обход всех моделей проекта.

    Модель, ссылающаяся одновременно на Student и на Candidate, восстанавливает
    пару «кто за кого проголосовал» независимо от названий полей.
    """

    def test_no_model_references_both_student_and_candidate(self):
        offenders = []
        for model in apps.get_models():
            if not model._meta.app_label.startswith(("voting", "students", "candidates",
                                                     "elections", "universities",
                                                     "accounts", "content", "core")):
                continue
            related = _related_models(model)
            if Student in related and Candidate in related:
                offenders.append(f"{model._meta.app_label}.{model.__name__}")
        self.assertEqual(
            offenders, [],
            f"модели связывают студента с кандидатом: {offenders}",
        )

    def test_no_model_references_both_voterecord_and_ballot(self):
        offenders = []
        for model in apps.get_models():
            related = _related_models(model)
            if VoteRecord in related and Ballot in related:
                offenders.append(f"{model._meta.app_label}.{model.__name__}")
        self.assertEqual(offenders, [], f"модели связывают участие с бюллетенем: {offenders}")


class NoSerializerExposesStudentAndCandidateTest(TestCase):
    """Обход всех сериализаторов проекта.

    Даже при корректной схеме админский API мог бы отдать структуру,
    соединяющую студента и кандидата в одном ответе.
    """

    def _all_serializer_classes(self):
        found = []
        for app_config in apps.get_app_configs():
            if not app_config.name.startswith("apps."):
                continue
            module_name = f"{app_config.name}.serializers"
            try:
                module = importlib.import_module(module_name)
            except ModuleNotFoundError:
                continue
            for attr in vars(module).values():
                if (
                    isinstance(attr, type)
                    and issubclass(attr, serializers.BaseSerializer)
                    and attr.__module__ == module_name
                ):
                    found.append(attr)
        return found

    def test_no_serializer_declares_both_student_and_candidate(self):
        offenders = []
        for cls in self._all_serializer_classes():
            fields = set(getattr(getattr(cls, "Meta", None), "fields", []) or [])
            fields |= set(getattr(cls, "_declared_fields", {}))
            lowered = {str(f).lower() for f in fields}
            has_student = any("student" in f for f in lowered)
            has_candidate = any("candidate" in f for f in lowered)
            if has_student and has_candidate:
                offenders.append(f"{cls.__module__}.{cls.__name__}")
        self.assertEqual(
            offenders, [],
            f"сериализаторы отдают студента и кандидата вместе: {offenders}",
        )

    def test_serializers_were_actually_discovered(self):
        """Страж самого теста: пустой список сделал бы проверку выше бессмысленной."""
        self.assertGreater(len(self._all_serializer_classes()), 5)


class VoteLoggingPrivacyTest(ContractTestCase):
    """ТЗ п.4: из логов нельзя восстановить выбор студента."""

    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.student = make_student(self.uni, student_id="S-1")
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)

    def test_successful_vote_logs_no_student_or_candidate(self):
        from apps.voting.services import cast_secret_ballot

        with self.assertLogs("apps.voting", level="INFO") as captured:
            cast_secret_ballot(self.student, str(self.election.id), str(self.candidate.id))

        blob = "\n".join(captured.output)
        self.assertIn(str(self.election.id), blob, "election_id полезен и разрешён")
        self.assertNotIn(str(self.student.id), blob, "student_id в логе голосования")
        self.assertNotIn(str(self.candidate.id), blob, "candidate_id в логе голосования")
        self.assertNotIn(self.student.student_id, blob)
        self.assertNotIn(self.candidate.full_name, blob)

    def test_model_str_reveals_neither_side(self):
        from apps.voting.models import Ballot, VoteRecord

        record = VoteRecord.objects.create(election=self.election, student=self.student)
        ballot = Ballot.objects.create(election=self.election, candidate=self.candidate)

        self.assertNotIn(self.student.student_id, str(record))
        self.assertNotIn(str(self.student.id), str(record))
        self.assertNotIn(self.candidate.full_name, str(ballot))
        self.assertNotIn(str(self.candidate.id), str(ballot))
