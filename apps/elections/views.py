import io
import uuid
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from django.utils import timezone
from django.http import HttpResponse
from rest_framework import generics, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from .models import Election
from .serializers import (
    ElectionSerializer, ElectionStudentSerializer,
    TurnoutSerializer, ElectionResultsSerializer
)
from apps.candidates.models import Candidate
from apps.students.models import Student
from apps.voting.models import VoteRecord, Ballot
from apps.core.permissions import IsAdminUserWithRole, IsStudentAuthenticated
from apps.accounts.models import AdminActionLog

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')

# --- Admin Election Views ---

class AdminElectionListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAdminUserWithRole]
    serializer_class = ElectionSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'university']
    search_fields = ['title', 'title_ky', 'description']
    ordering_fields = ['starts_at', 'created_at', 'title']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        qs = Election.objects.all()
        if getattr(user, 'role', None) != 'super_admin' and not user.is_superuser:
            qs = qs.filter(university_id=user.university_id)
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        university = serializer.validated_data.get('university')
        if getattr(user, 'role', None) != 'super_admin' and not user.is_superuser:
            university = user.university
        election = serializer.save(created_by=user, university=university)
        AdminActionLog.objects.create(
            admin=user,
            action="create_election",
            target_type="election",
            target_id=str(election.id),
            details={"title": election.title, "university": election.university.code},
            ip_address=get_client_ip(self.request)
        )

class AdminElectionDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAdminUserWithRole]
    serializer_class = ElectionSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Election.objects.all()
        if getattr(user, 'role', None) != 'super_admin' and not user.is_superuser:
            qs = qs.filter(university_id=user.university_id)
        return qs

    def perform_update(self, serializer):
        election = serializer.save()
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="update_election",
            target_type="election",
            target_id=str(election.id),
            details={"title": election.title, "status": election.status},
            ip_address=get_client_ip(self.request)
        )

    def perform_destroy(self, instance):
        if instance.status == Election.Status.ACTIVE:
            return Response(
                {"error": {"code": "active_election", "message": "Невозможно удалить активные выборы. Сначала отмените или завершите их."}},
                status=status.HTTP_400_BAD_REQUEST
            )
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="delete_election",
            target_type="election",
            target_id=str(instance.id),
            details={"title": instance.title},
            ip_address=get_client_ip(self.request)
        )
        instance.delete()

class AdminElectionStartView(APIView):
    permission_classes = [IsAdminUserWithRole]

    def post(self, request, pk):
        try:
            election = Election.objects.get(id=pk)
        except Election.DoesNotExist:
            return Response({"error": {"code": "not_found", "message": "Выборы не найдены"}}, status=status.HTTP_404_NOT_FOUND)

        if election.candidates.count() < 1:
            return Response({"error": {"code": "no_candidates", "message": "Нельзя запустить выборы без кандидатов"}}, status=status.HTTP_400_BAD_REQUEST)

        election.status = Election.Status.ACTIVE
        election.save(update_fields=['status'])

        AdminActionLog.objects.create(
            admin=request.user,
            action="start_election",
            target_type="election",
            target_id=str(election.id),
            details={"title": election.title},
            ip_address=get_client_ip(request)
        )

        return Response({"success": True, "message": "Выборы успешно запущены", "status": election.status})

class AdminElectionFinishView(APIView):
    permission_classes = [IsAdminUserWithRole]

    def post(self, request, pk):
        try:
            election = Election.objects.get(id=pk)
        except Election.DoesNotExist:
            return Response({"error": {"code": "not_found", "message": "Выборы не найдены"}}, status=status.HTTP_404_NOT_FOUND)

        election.status = Election.Status.FINISHED
        election.save(update_fields=['status'])

        AdminActionLog.objects.create(
            admin=request.user,
            action="finish_election",
            target_type="election",
            target_id=str(election.id),
            details={"title": election.title},
            ip_address=get_client_ip(request)
        )

        return Response({"success": True, "message": "Выборы успешно завершены", "status": election.status})

class AdminElectionCancelView(APIView):
    permission_classes = [IsAdminUserWithRole]

    def post(self, request, pk):
        try:
            election = Election.objects.get(id=pk)
        except Election.DoesNotExist:
            return Response({"error": {"code": "not_found", "message": "Выборы не найдены"}}, status=status.HTTP_404_NOT_FOUND)

        election.status = Election.Status.CANCELLED
        election.save(update_fields=['status'])

        AdminActionLog.objects.create(
            admin=request.user,
            action="cancel_election",
            target_type="election",
            target_id=str(election.id),
            details={"title": election.title},
            ip_address=get_client_ip(request)
        )

        return Response({"success": True, "message": "Выборы отменены", "status": election.status})

class AdminElectionTurnoutView(APIView):
    permission_classes = [IsAdminUserWithRole]

    def get(self, request, pk):
        try:
            election = Election.objects.select_related('university').get(id=pk)
        except Election.DoesNotExist:
            return Response({"error": {"code": "not_found", "message": "Выборы не найдены"}}, status=status.HTTP_404_NOT_FOUND)

        total_eligible = Student.objects.filter(university=election.university, is_active=True).count()
        total_voted = VoteRecord.objects.filter(election=election).count()
        turnout_percent = round((total_voted / total_eligible * 100), 2) if total_eligible > 0 else 0.0

        candidates_data = []
        for candidate in election.candidates.all().order_by('order'):
            votes = Ballot.objects.filter(election=election, candidate=candidate).count()
            percent = round((votes / total_voted * 100), 1) if total_voted > 0 else 0.0

            photo_url = None
            if candidate.photo:
                try:
                    photo_url = request.build_absolute_uri(candidate.photo.url)
                except Exception:
                    photo_url = candidate.photo.url
            elif candidate.photo_url:
                photo_url = candidate.photo_url

            candidates_data.append({
                "candidate_id": str(candidate.id),
                "full_name": candidate.full_name,
                "photo": photo_url,
                "faculty": candidate.faculty,
                "course": candidate.course,
                "position": candidate.position,
                "short_bio": candidate.short_bio,
                "votes": votes,
                "percent": percent
            })

        # Sort descending by votes
        candidates_data.sort(key=lambda c: c['votes'], reverse=True)

        return Response({
            "election_id": str(election.id),
            "election_title": election.title,
            "status": election.status,
            "total_eligible": total_eligible,
            "total_voted": total_voted,
            "turnout_percent": turnout_percent,
            "candidates": candidates_data
        }, status=status.HTTP_200_OK)

class AdminElectionResultsView(APIView):
    permission_classes = [IsAdminUserWithRole]

    def get(self, request, pk):
        try:
            election = Election.objects.select_related('university').get(id=pk)
        except Election.DoesNotExist:
            return Response({"error": {"code": "not_found", "message": "Выборы не найдены"}}, status=status.HTTP_404_NOT_FOUND)

        # In accordance with Section 4.5 & 6.2: results are hidden until finished, unless explicitly configured
        if election.status != Election.Status.FINISHED and not election.results_visible_to_admin_before_finish:
            return Response({
                "error": {
                    "code": "results_hidden",
                    "message": "Результаты голосования скрыты до официального завершения выборов для соблюдения тайны и чистоты голосования"
                }
            }, status=status.HTTP_403_FORBIDDEN)

        total_eligible = Student.objects.filter(university=election.university, is_active=True).count()
        total_voted = Ballot.objects.filter(election=election).count()
        turnout_percent = round((total_voted / total_eligible * 100), 2) if total_eligible > 0 else 0.0

        candidates_data = []
        for candidate in election.candidates.all().order_by('order'):
            votes = Ballot.objects.filter(election=election, candidate=candidate).count()
            percent = round((votes / total_voted * 100), 2) if total_voted > 0 else 0.0
            candidates_data.append({
                "candidate_id": str(candidate.id),
                "full_name": candidate.full_name,
                "photo": candidate.photo.url if candidate.photo else None,
                "photo_url": candidate.photo_url,
                "faculty": candidate.faculty,
                "course": candidate.course,
                "position": candidate.position,
                "votes": votes,
                "percent": percent
            })

        # Sort by votes descending to show leader first
        candidates_data.sort(key=lambda c: c['votes'], reverse=True)

        return Response({
            "election_id": str(election.id),
            "election_title": election.title,
            "university_name": election.university.name,
            "total_eligible": total_eligible,
            "total_voted": total_voted,
            "turnout_percent": turnout_percent,
            "candidates": candidates_data
        }, status=status.HTTP_200_OK)

class AdminElectionResultsExportView(APIView):
    permission_classes = [IsAdminUserWithRole]

    def post(self, request, pk):
        try:
            election = Election.objects.select_related('university').get(id=pk)
        except Election.DoesNotExist:
            return Response({"error": {"code": "not_found", "message": "Выборы не найдены"}}, status=status.HTTP_404_NOT_FOUND)

        if election.status != Election.Status.FINISHED and not election.results_visible_to_admin_before_finish:
            return Response({"error": {"code": "results_hidden", "message": "Экспорт доступен только после завершения выборов"}}, status=status.HTTP_403_FORBIDDEN)

        total_eligible = Student.objects.filter(university=election.university, is_active=True).count()
        total_voted = Ballot.objects.filter(election=election).count()
        turnout_percent = round((total_voted / total_eligible * 100), 2) if total_eligible > 0 else 0.0

        # Build styled Excel document
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Итоги голосования"

        # Fonts & styling
        header_font = Font(name="Arial", size=14, bold=True, color="011C42")
        sub_font = Font(name="Arial", size=10, italic=True)
        table_header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        table_header_fill = PatternFill(start_color="011C42", end_color="011C42", fill_type="solid")
        border_thin = Border(
            left=Side(style='thin', color='C0C1C6'),
            right=Side(style='thin', color='C0C1C6'),
            top=Side(style='thin', color='C0C1C6'),
            bottom=Side(style='thin', color='C0C1C6')
        )

        ws.append(["ОФИЦИАЛЬНЫЙ ПРОТОКОЛ ИТОГОВ ГОЛОСОВАНИЯ"])
        ws.append([f"Выборы: {election.title}"])
        ws.append([f"Университет: {election.university.name}"])
        ws.append([f"Дата выгрузки: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}"])
        ws.append([])
        ws.append(["Показатель", "Значение"])
        ws.append(["Всего избирателей (студентов):", total_eligible])
        ws.append(["Всего проголосовало:", total_voted])
        ws.append(["Итоговая явка (%):", f"{turnout_percent}%"])
        ws.append([])
        ws.append(["Место", "Кандидат", "Факультет", "Курс", "Должность", "Голосов", "Процент"])

        # Candidate rows
        candidates_list = []
        for c in election.candidates.all():
            v = Ballot.objects.filter(election=election, candidate=c).count()
            p = round((v / total_voted * 100), 2) if total_voted > 0 else 0.0
            candidates_list.append((c, v, p))

        candidates_list.sort(key=lambda x: x[1], reverse=True)

        for rank, (cand, votes, pct) in enumerate(candidates_list, start=1):
            ws.append([rank, cand.full_name, cand.faculty, cand.course, cand.position, votes, f"{pct}%"])

        # Column widths
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="results_{election.id}.xlsx"'
        return response

# --- Student Available Elections Views ---

class StudentAvailableElectionsView(APIView):
    permission_classes = [IsStudentAuthenticated]

    def get(self, request):
        student = request.user.student
        now = timezone.now()

        # Find elections where student has voted
        voted_election_ids = set(VoteRecord.objects.filter(student=student).values_list('election_id', flat=True))

        include_all = request.query_params.get('all', 'false').lower() == 'true'

        if include_all:
            elections = Election.objects.filter(
                university=student.university
            ).exclude(status=Election.Status.DRAFT).order_by('-created_at')
        else:
            elections = Election.objects.filter(
                university=student.university,
                status=Election.Status.ACTIVE,
                starts_at__lte=now,
                ends_at__gte=now
            ).exclude(id__in=voted_election_ids).order_by('ends_at')

        serializer = ElectionStudentSerializer(elections, many=True, context={'request': request})
        data = serializer.data
        for item in data:
            try:
                item_uuid = uuid.UUID(str(item['id']))
                item['has_voted'] = item_uuid in voted_election_ids
            except (ValueError, TypeError):
                item['has_voted'] = False

        return Response(data, status=status.HTTP_200_OK)

class StudentElectionDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        try:
            election = Election.objects.select_related('university').get(id=pk)
        except Election.DoesNotExist:
            return Response({"error": {"code": "not_found", "message": "Выборы не найдены"}}, status=status.HTTP_404_NOT_FOUND)

        serializer = ElectionStudentSerializer(election, context={'request': request})
        data = serializer.data

        # If student is authenticated, check if student belongs to this uni and whether they voted
        student = getattr(request.user, 'student', None) if hasattr(request.user, 'student') else None
        if student:
            has_voted = VoteRecord.objects.filter(election=election, student=student).exists()
            data['has_voted'] = has_voted
            data['is_eligible'] = (student.university_id == election.university_id)
        else:
            data['has_voted'] = False
            data['is_eligible'] = None

        return Response(data, status=status.HTTP_200_OK)
