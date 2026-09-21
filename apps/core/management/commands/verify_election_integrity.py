"""Проверка целостности данных выборов (ТЗ п.87, 115).

КОГДА ЭТО НУЖНО
---------------
После любого нагрузочного прогона. ТЗ п.87 формулирует прямо: нагрузка
без последующей проверки целостности не считается валидным бенчмарком.
Красивые цифры RPS при разъехавшихся данных — не результат, а провал.

ЧЕГО ЭТА КОМАНДА НЕ ДЕЛАЕТ
--------------------------
Она **не пытается сопоставить студента с кандидатом** — ни для проверки,
ни для отчёта. Такое сопоставление разрушило бы тайну голосования,
ради защиты которой всё и строилось (ТЗ п.115).

Проверяется только то, что видно по отдельности: сколько записей об участии,
сколько бюллетеней, нет ли дублей и осиротевших ссылок.

    python manage.py verify_election_integrity            # все выборы
    python manage.py verify_election_integrity <id>       # конкретные
    python manage.py verify_election_integrity --expected-votes 5000
"""
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, F

from apps.candidates.models import Candidate
from apps.elections.models import Election
from apps.voting.models import Ballot, VoteRecord


class Command(BaseCommand):
    help = "Проверяет целостность данных голосования. Ничего не изменяет."

    def add_arguments(self, parser):
        parser.add_argument('election_id', nargs='?', default=None)
        parser.add_argument('--expected-votes', type=int, default=None,
                            help='Ожидаемое число принятых голосов (для проверки после нагрузки).')
        parser.add_argument('--quiet', action='store_true')

    def handle(self, *args, **opts):
        elections = Election.objects.all()
        if opts['election_id']:
            elections = elections.filter(id=opts['election_id'])
            if not elections.exists():
                raise CommandError(f"Выборы {opts['election_id']} не найдены")

        problems = []
        totals = {'records': 0, 'ballots': 0}

        for election in elections.order_by('created_at'):
            result = self._check_election(election, problems)
            totals['records'] += result['records']
            totals['ballots'] += result['ballots']
            if not opts['quiet']:
                self._print_election(election, result)

        problems.extend(self._check_global())

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Итого'))
        self.stdout.write(f"  записей об участии: {totals['records']}")
        self.stdout.write(f"  бюллетеней:         {totals['ballots']}")

        expected = opts['expected_votes']
        if expected is not None:
            self.stdout.write(f"  ожидалось голосов:  {expected}")
            if totals['records'] != expected:
                problems.append(
                    f"число принятых голосов {totals['records']} не совпадает "
                    f"с ожидаемым {expected}"
                )

        self.stdout.write('')
        if problems:
            self.stdout.write(self.style.ERROR(f'НАРУШЕНИЯ ЦЕЛОСТНОСТИ: {len(problems)}'))
            for problem in problems:
                self.stdout.write(f'  - {problem}')
            raise CommandError(
                'Данные повреждены. Результаты нагрузочного прогона недействительны.'
            )

        self.stdout.write(self.style.SUCCESS('Целостность подтверждена.'))

    # --- проверки ---

    def _check_election(self, election, problems):
        records = VoteRecord.objects.filter(election=election).count()
        ballots = Ballot.objects.filter(election=election).count()

        if records != ballots:
            # Главный инвариант: голос создаёт ровно одну запись об участии
            # и ровно один бюллетень в одной транзакции (ТЗ п.5)
            problems.append(
                f"{election.title}: записей об участии {records}, "
                f"бюллетеней {ballots} — частично записанные голоса"
            )

        duplicates = (
            VoteRecord.objects.filter(election=election)
            .values('student_id').annotate(n=Count('id')).filter(n__gt=1).count()
        )
        if duplicates:
            problems.append(f"{election.title}: студентов с двумя голосами — {duplicates}")

        orphans = Ballot.objects.filter(election=election).exclude(
            candidate__election_id=election.id
        ).count()
        if orphans:
            problems.append(
                f"{election.title}: бюллетеней с кандидатом чужих выборов — {orphans}"
            )

        foreign = VoteRecord.objects.filter(election=election).exclude(
            student__university_id=election.university_id
        ).count()
        if foreign:
            problems.append(
                f"{election.title}: голосов от студентов другого вуза — {foreign}"
            )

        return {'records': records, 'ballots': ballots, 'duplicates': duplicates,
                'orphans': orphans, 'foreign': foreign}

    def _check_global(self):
        problems = []

        dangling = Ballot.objects.filter(candidate__isnull=True).count()
        if dangling:
            problems.append(f"бюллетеней без кандидата: {dangling}")

        mismatched = Candidate.objects.exclude(
            university_id=F('election__university_id')
        ).count()
        if mismatched:
            problems.append(f"кандидатов с чужим вузом: {mismatched}")

        return problems

    def _print_election(self, election, result):
        ok = not (result['duplicates'] or result['orphans'] or result['foreign']
                  or result['records'] != result['ballots'])
        mark = self.style.SUCCESS('OK  ') if ok else self.style.ERROR('ОШИБКА')
        self.stdout.write(
            f"  {mark} {election.title[:34]:34} "
            f"участий={result['records']:>7} бюллетеней={result['ballots']:>7}"
        )
