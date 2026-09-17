from rest_framework import serializers
from .models import Candidate

class CandidateSerializer(serializers.ModelSerializer):
    university_name = serializers.CharField(source='university.name', read_only=True)
    election_title = serializers.CharField(source='election.title', read_only=True)

    class Meta:
        model = Candidate
        fields = [
            'id', 'election', 'election_title', 'university', 'university_name',
            'full_name', 'photo', 'photo_url', 'faculty', 'course',
            'position', 'short_bio', 'program', 'order', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'university']
        extra_kwargs = {
            'election': {'required': False},
            'faculty': {'required': False, 'allow_blank': True},
            'course': {'required': False},
            'position': {'required': False, 'allow_blank': True},
            'photo': {'required': False},
            'photo_url': {'required': False, 'allow_blank': True},
            'short_bio': {'required': False, 'allow_blank': True},
            'program': {'required': False, 'allow_blank': True},
        }

    def create(self, validated_data):
        if 'election' in validated_data and 'university' not in validated_data:
            validated_data['university'] = validated_data['election'].university
        return super().create(validated_data)

class CandidatePublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Candidate
        fields = [
            'id', 'full_name', 'photo', 'photo_url', 'faculty', 'course',
            'position', 'short_bio', 'program', 'order'
        ]

class CandidateReorderSerializer(serializers.Serializer):
    ordered_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False
    )
