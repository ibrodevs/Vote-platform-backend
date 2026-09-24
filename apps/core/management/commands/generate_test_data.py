"""Генератор синтетических данных (ТЗ п.78).

ЗАЧЕМ
-----
Планировщик PostgreSQL на таблице в 19 строк всегда выбирает Seq Scan:
прочитать одну страницу дешевле, чем идти в индекс. Любой вывод об индексах,
сделанный на таких данных, будет неверным. Для анализа планов нужен объём,
сопоставимый с production.

НИКАКИХ НАСТОЯЩИХ ПЕРСОНАЛЬНЫХ ДАННЫХ
-------------------------------------
Имена собираются из фиксированных списков, телефоны берутся из диапазона,
не выдаваемого операторами, email — на домене .invalid (RFC 2606, домен
гарантированно не существует).

ИНВАРИАНТ ГОЛОСОВАНИЯ СОБЛЮДАЕТСЯ
---------------------------------
На каждый VoteRecord создаётся ровно один Ballot. Генератор, ломающий
инвариант, обесценил бы все последующие проверки целостности.

    python manage.py generate_test_data --students 200000 --elections 60
    python manage.py generate_test_data --clear
"""
import random
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.candidates.models import Candidate
from apps.elections.models import Election
from apps.students.models import Student
from apps.universities.models import University
from apps.voting.models import Ballot, VoteRecord

# Префикс, по которому сгенерированные данные отличаются от настоящих.
# --clear удаляет только их.
SYNTHETIC_PREFIX = "synthetic-"

BATCH_SIZE = 5000

FIRST = ["Асан", "Айпери", "Бекзат", "Гульнара", "Данияр", "Жамиля", "Искендер",
         "Каныкей", "Мирлан", "Нурзат", "Омурбек", "Рахат", "Салтанат", "Тилек",
         "Улан", "Чолпон", "Эльмира", "Азамат", "Бермет", "Кубанычбек"]
LAST = ["Асанов", "Бекова", "Джумабаев", "Иманалиев", "Касымова", "Мамытов",
        "Нурланова", "Осмонов", "Сыдыкова", "Токтогулов", "Абдыкадыров",
        "Байсалова", "Эркинбеков", "Жумагулова", "Кадыров"]
FACULTIES = ["Информационные технологии", "Экономика и бизнес", "Инженерия",
             "Юриспруденция", "Медицина", "Педагогика", "Архитектура"]


class Command(BaseCommand):
    help = "Генерирует синтетические данные для анализа планов запросов и бенчмарков."

    def add_arguments(self, parser):
        parser.add_argument("--universities", type=int, default=20)
        parser.add_argument("--students", type=int, default=200_000)
        parser.add_argument("--elections", type=int, default=60)
        parser.add_argument("--candidates-per-election", type=int, default=10)
        parser.add_argument(
            "--vote-ratio", type=float, default=0.6,
            help="Доля студентов, проголосовавших в активных выборах своего вуза.",
        )
        parser.add_argument("--seed", type=int, default=20260920)
        parser.add_argument("--clear", action="store_true",
                            help="Удалить ранее сгенерированные данные и выйти.")

    def handle(self, *args, **opts):
        random.seed(opts["seed"])

        if opts["clear"]:
            return self._clear()

        if opts["vote_ratio"] < 0 or opts["vote_ratio"] > 1:
            raise CommandError("--vote-ratio должен быть от 0 до 1")

        started = timezone.now()
        universities = self._make_universities(opts["universities"])
        students = self._make_students(universities, opts["students"])
        elections = self._make_elections(universities, opts["elections"])
        candidates = self._make_candidates(elections, opts["candidates_per_election"])
        votes = self._make_votes(elections, candidates, students, opts["vote_ratio"])

        elapsed = (timezone.now() - started).total_seconds()
        self.stdout.write(self.style.SUCCESS(
            f"\nГотово за {elapsed:.1f} с: "
            f"{len(universities)} вузов, {len(students)} студентов, "
            f"{len(elections)} выборов, {len(candidates)} кандидатов, {votes} голосов"
        ))
        self.stdout.write(
            "Удалить: python manage.py generate_test_data --clear\n"
            "Проанализировать планы: python manage.py explain_hot_queries"
        )

    # --- генерация ---

    def _make_universities(self, count):
        existing = set(
            University.objects.filter(code__startswith=SYNTHETIC_PREFIX)
            .values_list("code", flat=True)
        )
        to_create = [
            University(
                name=f"Синтетический университет {i}",
                name_ky=f"Синтетикалык университет {i}",
                code=f"{SYNTHETIC_PREFIX}uni-{i:03d}",
            )
            for i in range(count)
            if f"{SYNTHETIC_PREFIX}uni-{i:03d}" not in existing
        ]
        University.objects.bulk_create(to_create, batch_size=BATCH_SIZE)
        result = list(University.objects.filter(code__startswith=SYNTHETIC_PREFIX).order_by("code"))
        self.stdout.write(f"  университетов: {len(result)}")
        return result

    def _make_students(self, universities, count):
        Student.objects.filter(student_id__startswith=SYNTHETIC_PREFIX).delete()
        batch, created = [], 0
        for i in range(count):
            uni = universities[i % len(universities)]
            batch.append(Student(
                university=uni,
                student_id=f"{SYNTHETIC_PREFIX}{i:08d}",
                full_name=f"{random.choice(LAST)} {random.choice(FIRST)}",
                # Диапазон +99677700xxxx операторами не выдаётся
                phone_number=f"+9967770{i % 100000:05d}",
                # .invalid зарезервирован RFC 2606 и не существует
                email=f"{SYNTHETIC_PREFIX}{i:08d}@example.invalid",
                faculty=random.choice(FACULTIES),
                group=f"ГР-{i % 500:03d}",
                course=random.randint(1, 5),
                is_active=(i % 50 != 0),  # ~2% неактивных, как в жизни
            ))
            if len(batch) >= BATCH_SIZE:
                Student.objects.bulk_create(batch, batch_size=BATCH_SIZE)
                created += len(batch)
                batch = []
                self.stdout.write(f"  студентов: {created}", ending="\r")
        if batch:
            Student.objects.bulk_create(batch, batch_size=BATCH_SIZE)
            created += len(batch)
        self.stdout.write(f"  студентов: {created}    ")
        return list(Student.objects.filter(student_id__startswith=SYNTHETIC_PREFIX).only("id", "university_id"))

    def _make_elections(self, universities, count):
        Election.objects.filter(title__startswith=SYNTHETIC_PREFIX).delete()
        now = timezone.now()
        batch = []
        for i in range(count):
            uni = universities[i % len(universities)]
            # Смесь статусов: планировщику нужна реалистичная селективность
            if i % 4 == 0:
                status, starts, ends = Election.Status.ACTIVE, now - timedelta(hours=2), now + timedelta(days=3)
            elif i % 4 == 1:
                status, starts, ends = Election.Status.FINISHED, now - timedelta(days=30), now - timedelta(days=29)
            elif i % 4 == 2:
                status, starts, ends = Election.Status.DRAFT, now + timedelta(days=10), now + timedelta(days=12)
            else:
                status, starts, ends = Election.Status.SCHEDULED, now + timedelta(days=1), now + timedelta(days=4)
            batch.append(Election(
                university=uni,
                title=f"{SYNTHETIC_PREFIX}Выборы {i:03d}",
                title_ky=f"{SYNTHETIC_PREFIX}Шайлоо {i:03d}",
                status=status, starts_at=starts, ends_at=ends,
            ))
        Election.objects.bulk_create(batch, batch_size=BATCH_SIZE)
        result = list(Election.objects.filter(title__startswith=SYNTHETIC_PREFIX))
        self.stdout.write(f"  выборов: {len(result)}")
        return result

    def _make_candidates(self, elections, per_election):
        batch = []
        for election in elections:
            for j in range(per_election):
                batch.append(Candidate(
                    election=election,
                    university_id=election.university_id,
                    full_name=f"{random.choice(LAST)} {random.choice(FIRST)}",
                    faculty=random.choice(FACULTIES),
                    course=random.randint(2, 5),
                    order=j,
                ))
        Candidate.objects.bulk_create(batch, batch_size=BATCH_SIZE)
        self.stdout.write(f"  кандидатов: {len(batch)}")
        return batch

    def _make_votes(self, elections, candidates, students, ratio):
        """Голоса с соблюдением инварианта: 1 VoteRecord <-> 1 Ballot."""
        by_university = {}
        for student in students:
            by_university.setdefault(student.university_id, []).append(student)

        by_election = {}
        for candidate in candidates:
            by_election.setdefault(candidate.election_id, []).append(candidate)

        total = 0
        for election in elections:
            if election.status not in (Election.Status.ACTIVE, Election.Status.FINISHED):
                continue
            pool = by_university.get(election.university_id, [])
            election_candidates = by_election.get(election.id, [])
            if not pool or not election_candidates:
                continue

            voters = pool[: int(len(pool) * ratio)]
            records, ballots = [], []
            for student in voters:
                records.append(VoteRecord(election_id=election.id, student_id=student.id))
                ballots.append(Ballot(
                    election_id=election.id,
                    candidate_id=random.choice(election_candidates).id,
                ))
            VoteRecord.objects.bulk_create(records, batch_size=BATCH_SIZE)
            Ballot.objects.bulk_create(ballots, batch_size=BATCH_SIZE)
            total += len(records)
            self.stdout.write(f"  голосов: {total}", ending="\r")

        self.stdout.write(f"  голосов: {total}    ")
        return total

    # --- очистка ---

    def _clear(self):
        with transaction.atomic():
            elections = Election.objects.filter(title__startswith=SYNTHETIC_PREFIX)
            ballots, _ = Ballot.objects.filter(election__in=elections).delete()
            records, _ = VoteRecord.objects.filter(election__in=elections).delete()
            candidates, _ = Candidate.objects.filter(election__in=elections).delete()
            n_elections, _ = elections.delete()
            students, _ = Student.objects.filter(student_id__startswith=SYNTHETIC_PREFIX).delete()
            unis, _ = University.objects.filter(code__startswith=SYNTHETIC_PREFIX).delete()
        self.stdout.write(self.style.SUCCESS(
            f"Удалено синтетических объектов: выборы {n_elections}, студенты {students}, "
            f"вузы {unis}, кандидаты {candidates}, голоса {records}/{ballots}"
        ))
