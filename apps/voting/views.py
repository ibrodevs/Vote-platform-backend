from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from apps.core.permissions import IsStudentAuthenticated
from .serializers import CastVoteSerializer, VoteStatusSerializer
from .services import cast_secret_ballot, VotingError
from .models import VoteRecord

class CastVoteView(APIView):
    permission_classes = [IsStudentAuthenticated]

    def post(self, request):
        serializer = CastVoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        election_id = serializer.validated_data['election_id']
        candidate_id = serializer.validated_data['candidate_id']
        student = request.user.student

        try:
            cast_secret_ballot(student, election_id, candidate_id)
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

    def get(self, request, election_id):
        student = request.user.student
        record = VoteRecord.objects.filter(election_id=election_id, student=student).first()
        return Response({
            "has_voted": bool(record),
            "voted_at": record.voted_at if record else None
        }, status=status.HTTP_200_OK)
