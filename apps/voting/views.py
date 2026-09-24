from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from apps.core import metrics
from apps.core.permissions import IsStudentAuthenticated
from apps.core.throttling import StudentActionThrottle, VoteThrottle
from .serializers import CastVoteSerializer, VoteStatusSerializer
from .services import cast_secret_ballot, vote_status, VotingError

class CastVoteView(APIView):
    permission_classes = [IsStudentAuthenticated]
    # Ключ — студент, не IP: иначе пять тысяч студентов за университетским
    # NAT заблокировали бы друг друга (ТЗ п.36).
    throttle_classes = [VoteThrottle]

    def post(self, request):
        serializer = CastVoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        election_id = serializer.validated_data['election_id']
        candidate_id = serializer.validated_data['candidate_id']
        # Принципал из кэша, а не request.user.student: обращение к полной
        # модели стоило бы лишнего SELECT на каждом голосе (ТЗ п.18, 48).
        voter = request.user.principal

        try:
            cast_secret_ballot(voter, election_id, candidate_id)
            # Метка — только выборы и исход. Ни студента, ни кандидата:
            # счётчик по кандидату, растущий синхронно с записью об участии,
            # восстановил бы выбор студента (ТЗ п.63).
            metrics.record_vote_attempt(election_id, 'accepted')
            return Response({
                "success": True,
                "message": "Ваш голос успешно и анонимно принят"
            }, status=status.HTTP_200_OK)
        except VotingError as e:
            metrics.record_vote_attempt(election_id, e.code)
            return Response({
                "error": {
                    "code": e.code,
                    "message": e.message
                }
            }, status=status.HTTP_400_BAD_REQUEST)

class VoteStatusView(APIView):
    permission_classes = [IsStudentAuthenticated]
    throttle_classes = [StudentActionThrottle]

    def get(self, request, election_id):
        # Вся политика кэширования статуса — в сервисе, рядом с местом,
        # где эта же запись создаётся (ТЗ п.104).
        has_voted, voted_at = vote_status(request.user.id, election_id)
        return Response({
            "has_voted": has_voted,
            "voted_at": voted_at,
        }, status=status.HTTP_200_OK)
