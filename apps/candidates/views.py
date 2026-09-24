from rest_framework import generics, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from .models import Candidate
from .serializers import CandidateSerializer, CandidatePublicSerializer, CandidateReorderSerializer
from apps.elections.models import Election
from apps.core.cache_invalidation import invalidate_candidate, invalidate_election
from apps.core.permissions import IsAdminUserWithRole, IsStudentAuthenticated, IsNotObserver
from apps.accounts.models import AdminActionLog

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')

class AdminElectionCandidatesListView(generics.ListCreateAPIView):
    permission_classes = [IsAdminUserWithRole]
    serializer_class = CandidateSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = None

    def get_queryset(self):
        election_id = self.kwargs.get('election_id')
        user = self.request.user
        # CandidateSerializer читает election.title и university.name —
        # без select_related это два запроса на каждого кандидата списка.
        qs = Candidate.objects.select_related('election', 'university').filter(
            election_id=election_id
        )
        if getattr(user, 'role', None) != 'super_admin' and not user.is_superuser:
            qs = qs.filter(university_id=user.university_id)
        return qs.order_by('order', 'created_at')

    def perform_create(self, serializer):
        election_id = self.kwargs.get('election_id')
        election = Election.objects.get(id=election_id)
        candidate = serializer.save(election=election, university=election.university)
        invalidate_candidate(candidate)
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="create_candidate",
            target_type="candidate",
            target_id=str(candidate.id),
            details={"full_name": candidate.full_name, "election": election.title},
            ip_address=get_client_ip(self.request)
        )

class AdminCandidateDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAdminUserWithRole]
    serializer_class = CandidateSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    queryset = Candidate.objects.select_related('election', 'university').all()

    def perform_update(self, serializer):
        candidate = serializer.save()
        invalidate_candidate(candidate)
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="update_candidate",
            target_type="candidate",
            target_id=str(candidate.id),
            details={"full_name": candidate.full_name},
            ip_address=get_client_ip(self.request)
        )

    def perform_destroy(self, instance):
        invalidate_candidate(instance)
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="delete_candidate",
            target_type="candidate",
            target_id=str(instance.id),
            details={"full_name": instance.full_name},
            ip_address=get_client_ip(self.request)
        )
        instance.delete()

class AdminCandidateReorderView(APIView):
    permission_classes = [IsAdminUserWithRole, IsNotObserver]

    def post(self, request, election_id):
        serializer = CandidateReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ordered_ids = serializer.validated_data['ordered_ids']

        for index, candidate_id in enumerate(ordered_ids):
            Candidate.objects.filter(id=candidate_id, election_id=election_id).update(order=index)
        invalidate_election(election_id)

        return Response({"success": True, "message": "Порядок кандидатов обновлен"}, status=status.HTTP_200_OK)

class StudentElectionCandidatesListView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, election_id):
        try:
            election = Election.objects.get(id=election_id)
        except Election.DoesNotExist:
            return Response({"error": {"code": "not_found", "message": "Выборы не найдены"}}, status=status.HTTP_404_NOT_FOUND)

        candidates = Candidate.objects.select_related('election', 'university').filter(
            election_id=election.id
        ).order_by('order', 'created_at')
        serializer = CandidatePublicSerializer(candidates, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

class CandidatePublicDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = CandidatePublicSerializer
    queryset = Candidate.objects.select_related('election', 'university').all()
