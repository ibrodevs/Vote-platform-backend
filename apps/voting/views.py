from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from apps.core.cache import safe_get, safe_set
from apps.core.cache_keys import student_vote_status
from apps.core.cache_policy import CachePolicy
from apps.core.permissions import IsStudentAuthenticated
from apps.core.throttling import StudentActionThrottle, VoteThrottle
from .serializers import CastVoteSerializer, VoteStatusSerializer
from .services import cast_secret_ballot, VotingError
from .models import VoteRecord

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
            return Response({
                "success": True,
                "message": "Ваш голос успешно и анонимно принят"
            }, status=status.HTTP_200_OK)
        except VotingError as e:
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
        # Положительный кэш (ТЗ п.21): факт участия необратим, поэтому
        # закэшированное «да» устареть не может. Отрицательного кэша нет —
        # см. обоснование в apps/core/cache_policy.py.
        cache_key = student_vote_status(request.user.id, election_id)
        cached = safe_get(cache_key)
        if cached is not None:
            # В кэше лежит метка времени голоса — ответ обязан совпадать
            # с тем, что вернулось бы из базы.
            return Response({
                "has_voted": True,
                "voted_at": cached,
            }, status=status.HTTP_200_OK)

        record = VoteRecord.objects.filter(
            election_id=election_id, student_id=request.user.id
        ).first()

        if record is not None:
            # Промах при существующей записи: восстанавливаем кэш.
            # Так он самовосстанавливается после очистки Redis.
            safe_set(cache_key, record.voted_at, timeout=CachePolicy.VOTE_STATUS_POSITIVE)

        return Response({
            "has_voted": bool(record),
            "voted_at": record.voted_at if record else None
        }, status=status.HTTP_200_OK)
