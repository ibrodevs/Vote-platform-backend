from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.accounts.models import AdminUser
from apps.universities.models import University
from apps.students.models import Student
from apps.elections.models import Election
from apps.candidates.models import Candidate
from apps.voting.models import VoteRecord, Ballot

class Command(BaseCommand):
    help = 'Populates the database with realistic demo universities, admins, students, elections, and candidates'

    def handle(self, *args, **options):
        self.stdout.write("Starting demo data seeding...")
        now = timezone.now()

        # 1. Universities
        kstu, _ = University.objects.get_or_create(
            code='kstu',
            defaults={
                'name': 'Кыргызский государственный технический университет им. И. Раззакова',
                'name_ky': 'И. Раззаков атындагы Кыргыз мамлекеттик техникалык университети',
                'is_active': True,
            }
        )
        auca, _ = University.objects.get_or_create(
            code='auca',
            defaults={
                'name': 'Американский университет в Центральной Азии',
                'name_ky': 'Борбордук Азиядагы Америка Университети',
                'is_active': True,
            }
        )
        self.stdout.write(self.style.SUCCESS(f"Universities: {kstu.code}, {auca.code}"))

        # 2. Admins
        # Super Admin
        if not AdminUser.objects.filter(email='admin@vote.kg').exists():
            AdminUser.objects.create_superuser(
                email='admin@vote.kg',
                password='adminpassword123',
                full_name='Супер Администратор Системы',
                role=AdminUser.Role.SUPER_ADMIN,
            )
        # KSTU Admin
        if not AdminUser.objects.filter(email='kstu_admin@vote.kg').exists():
            AdminUser.objects.create_user(
                email='kstu_admin@vote.kg',
                password='adminpassword123',
                full_name='Уполномоченный ЦИК КГТУ',
                role=AdminUser.Role.UNIVERSITY_ADMIN,
                university=kstu
            )
        # AUCA Admin
        if not AdminUser.objects.filter(email='auca_admin@vote.kg').exists():
            AdminUser.objects.create_user(
                email='auca_admin@vote.kg',
                password='adminpassword123',
                full_name='Dean of Students AUCA',
                role=AdminUser.Role.UNIVERSITY_ADMIN,
                university=auca
            )
        self.stdout.write(self.style.SUCCESS("Admins created: admin@vote.kg, kstu_admin@vote.kg, auca_admin@vote.kg (pass: adminpassword123)"))

        # 3. Students for KSTU
        kstu_students_data = [
            ("2024001", "Асанов Бектур Алмазович", "+996700111001", "Факультет информационных технологий", 3),
            ("2024002", "Иманалиева Айсулуу Касымовна", "+996700111002", "Инженерно-экономический факультет", 2),
            ("2024003", "Жусупов Эркин Даниярович", "+996700111003", "Энергетический факультет", 4),
            ("2024004", "Курманбекова Нагима Бакытовна", "+996700111004", "Факультет информационных технологий", 1),
            ("2024005", "Султанов Тимур Айбекович", "+996700111005", "Факультет транспорта и машиностроения", 3),
            ("2024006", "Осмонова Чолпон Кадыровна", "+996700111006", "Горно-металлургический институт", 2),
            ("2024007", "Токтогулов Данияр Саматович", "+996700111007", "Инженерно-экономический факультет", 3),
            ("2024008", "Алишерова Гульзада Мелисовна", "+996700111008", "Факультет информационных технологий", 2),
            ("2024009", "Бакиров Азамат Жаныбекович", "+996700111009", "Энергетический факультет", 1),
            ("2024010", "Мамытова Айгерим Нурлановна", "+996700111010", "Технологический факультет", 4),
            ("2024011", "Касымов Адилет Эркинович", "+996700111011", "Факультет информационных технологий", 2),
            ("2024012", "Нурматова Салтанат Кубанычбековна", "+996700111012", "Инженерно-экономический факультет", 3),
            ("2024013", "Садыков Руслан Эсенович", "+996700111013", "Факультет транспорта и машиностроения", 2),
            ("2024014", "Ташматова Жибек Асылбековна", "+996700111014", "Горно-металлургический институт", 1),
            ("2024015", "Эргешов Мухаммед Бактыбекович", "+996700111015", "Энергетический факультет", 3),
        ]

        created_students = []
        for s_id, name, phone, fac, crs in kstu_students_data:
            stud, _ = Student.objects.update_or_create(
                university=kstu,
                student_id=s_id,
                defaults={
                    'full_name': name,
                    'phone_number': phone,
                    'faculty': fac,
                    'course': crs,
                    'is_active': True
                }
            )
            created_students.append(stud)

        # Students for AUCA
        auca_students_data = [
            ("AUCA001", "Smith Jonathan", "+996555111222", "Software Engineering", 2),
            ("AUCA002", "Абдыкадырова Малика", "+996555222333", "Business Administration", 3),
            ("AUCA003", "Тен Александр", "+996555333444", "International Relations", 4),
        ]
        for s_id, name, phone, fac, crs in auca_students_data:
            Student.objects.update_or_create(
                university=auca,
                student_id=s_id,
                defaults={
                    'full_name': name,
                    'phone_number': phone,
                    'faculty': fac,
                    'course': crs,
                    'is_active': True
                }
            )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(created_students)} students for KSTU and {len(auca_students_data)} for AUCA."))

        # 4. KSTU Active Election
        active_election, _ = Election.objects.get_or_create(
            university=kstu,
            title="Выборы Президента Студенческого Сената 2026-2027",
            defaults={
                'title_ky': "Студенттик Сенаттын Президентин шайлоо 2026-2027",
                'description': "Ежегодные прямые тайные выборы студенческого лидера КГТУ им. Раззакова. Голосуйте ответственно!",
                'description_ky': "И. Раззаков атындагы КМТУнун студенттик лидерин жыл сайын өтүүчү түз жана жашыруун шайлоосу. Жоопкерчилик менен добуш бериңиз!",
                'status': Election.Status.ACTIVE,
                'starts_at': now - timedelta(hours=2),
                'ends_at': now + timedelta(days=2),
                'results_visible_to_admin_before_finish': False,
            }
        )

        # Candidates for KSTU Active Election
        candidates_data = [
            {
                "full_name": "Айбек Исаков",
                "faculty": "Факультет информационных технологий",
                "course": 3,
                "position": "Президент студенческого сената",
                "photo_url": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400&auto=format&fit=crop&q=80",
                "short_bio": "Активист Enactus, разработчик кампусного приложения KSTU Mobile, победитель хакатона TechFest 2025.",
                "program": """### Программа «Цифровой кампус и студенческие возможности»
1. **Бесшовный Wi-Fi**: Установка скоростных роутеров во всех корпусах и общежитиях.
2. **Прозрачность стипендий**: Открытый трекинг баллов за научную и общественную деятельность.
3. **Менторский клуб**: Программа стажировок от ведущих IT-компаний Бишкека.""",
                "order": 0
            },
            {
                "full_name": "Перизат Жумабаева",
                "faculty": "Инженерно-экономический факультет",
                "course": 2,
                "position": "Президент студенческого сената",
                "photo_url": "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=400&auto=format&fit=crop&q=80",
                "short_bio": "Лидер дебатного клуба КГТУ, организатор благотворительных ярмарок и экологических инициатив 'Зеленый политех'.",
                "program": """### Программа «Комфорт, экология и студенческое самоуправление»
1. **Обновление коворкингов**: Создание 3 новых круглосуточных пространств для подготовки к сессии.
2. **Эко-кампус**: Раздельный сбор пластика и макулатуры, установка кулеров с фильтрованной водой.
3. **Студенческий бюджет**: 20% бюджета сената распределяется открытым голосованием студентов.""",
                "order": 1
            },
            {
                "full_name": "Нурсултан Кадыров",
                "faculty": "Энергетический факультет",
                "course": 4,
                "position": "Президент студенческого сената",
                "photo_url": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400&auto=format&fit=crop&q=80",
                "short_bio": "Капитан университетской сборной по волейболу, староста общежития №2, отличник учебы.",
                "program": """### Программа «Спорт, поддержка общежитий и социальная защита»
1. **Реновация общежитий**: Замена сантехники, организация прачечных и зон отдыха.
2. **Спортивная лига**: Ежемесячные межфакультетские турниры с денежными призами.
3. **Юридическая помощь**: Консультации по защите прав студентов при прохождении практики.""",
                "order": 2
            }
        ]

        for cand_info in candidates_data:
            Candidate.objects.update_or_create(
                election=active_election,
                full_name=cand_info['full_name'],
                defaults={
                    'university': kstu,
                    'faculty': cand_info['faculty'],
                    'course': cand_info['course'],
                    'position': cand_info['position'],
                    'photo_url': cand_info['photo_url'],
                    'short_bio': cand_info['short_bio'],
                    'program': cand_info['program'],
                    'order': cand_info['order']
                }
            )
        self.stdout.write(self.style.SUCCESS(f"Active election '{active_election.title}' configured with 3 candidates."))

        # 5. KSTU Finished Election (to demonstrate past results and protocol download)
        finished_election, _ = Election.objects.get_or_create(
            university=kstu,
            title="Выборы в Молодежный Комитет КГТУ 2025",
            defaults={
                'title_ky': "КМТУ Жаштар Комитетине шайлоо 2025",
                'description': "Выборы членов молодежного комитета КГТУ за прошлый семестр. Итоги подведены.",
                'description_ky': "КМТУнун жаштар комитетинин мүчөлөрүн шайлоо. Жыйынтыктар чыгарылды.",
                'status': Election.Status.FINISHED,
                'starts_at': now - timedelta(days=30),
                'ends_at': now - timedelta(days=28),
                'results_visible_to_admin_before_finish': False,
            }
        )

        # Finished election candidates & ballots
        cand_a, _ = Candidate.objects.get_or_create(
            election=finished_election,
            full_name="Дастан Темиров",
            defaults={
                'university': kstu,
                'faculty': "Факультет информационных технологий",
                'course': 4,
                'position': "Председатель молодежного комитета",
                'photo_url': "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=400&auto=format&fit=crop&q=80",
                'short_bio': "Основатель IT-клуба",
                'order': 0
            }
        )
        cand_b, _ = Candidate.objects.get_or_create(
            election=finished_election,
            full_name="Алина Сабирова",
            defaults={
                'university': kstu,
                'faculty': "Технологический факультет",
                'course': 3,
                'position': "Председатель молодежного комитета",
                'photo_url': "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=400&auto=format&fit=crop&q=80",
                'short_bio': "Куратор культурных проектов",
                'order': 1
            }
        )

        # Seed anonymized ballots for the finished election if empty
        if Ballot.objects.filter(election=finished_election).count() == 0:
            for _ in range(8):
                Ballot.objects.create(election=finished_election, candidate=cand_a)
            for _ in range(4):
                Ballot.objects.create(election=finished_election, candidate=cand_b)
            # Seed participation records for 12 students (NO CANDIDATE REFERENCE)
            for s in created_students[:12]:
                VoteRecord.objects.get_or_create(election=finished_election, student=s)

        self.stdout.write(self.style.SUCCESS(f"Finished election '{finished_election.title}' seeded with sample results."))
        self.stdout.write(self.style.SUCCESS("All demo data seeded successfully!"))
