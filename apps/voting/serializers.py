from rest_framework import serializers

class CastVoteSerializer(serializers.Serializer):
    election_id = serializers.UUIDField()
    candidate_id = serializers.UUIDField()

class VoteStatusSerializer(serializers.Serializer):
    has_voted = serializers.BooleanField()
    voted_at = serializers.DateTimeField(required=False, allow_null=True)
