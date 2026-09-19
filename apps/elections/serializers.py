from rest_framework import serializers
from .models import Election
from apps.candidates.serializers import CandidatePublicSerializer
from apps.universities.serializers import UniversityShortSerializer

class ElectionSerializer(serializers.ModelSerializer):
    university_details = UniversityShortSerializer(source='university', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True, default='')
    candidates_count = serializers.SerializerMethodField()
    is_voting_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = Election
        fields = [
            'id', 'university', 'university_details', 'title', 'title_ky',
            'description', 'description_ky', 'status', 'starts_at', 'ends_at',
            'results_visible_to_admin_before_finish',
            'is_featured', 'featured_order', 'cover_image', 'cover_image_url',
            'created_by', 'created_by_name',
            'candidates_count', 'is_voting_open', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def get_candidates_count(self, obj):
        return obj.candidates.count()

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get('request')
        if instance.cover_image:
            if request:
                ret['cover_image'] = request.build_absolute_uri(instance.cover_image.url)
            else:
                ret['cover_image'] = instance.cover_image.url
        elif instance.cover_image_url:
            ret['cover_image'] = instance.cover_image_url
        else:
            ret['cover_image'] = ''
        return ret

class ElectionStudentSerializer(serializers.ModelSerializer):
    candidates = CandidatePublicSerializer(many=True, read_only=True)
    university_name = serializers.CharField(source='university.name', read_only=True)
    university_name_ky = serializers.CharField(source='university.name_ky', read_only=True)

    class Meta:
        model = Election
        fields = [
            'id', 'university', 'university_name', 'university_name_ky',
            'title', 'title_ky', 'description', 'description_ky',
            'status', 'starts_at', 'ends_at', 'candidates'
        ]

class TurnoutSerializer(serializers.Serializer):
    election_id = serializers.UUIDField()
    election_title = serializers.CharField()
    status = serializers.CharField()
    total_eligible = serializers.IntegerField()
    total_voted = serializers.IntegerField()
    turnout_percent = serializers.FloatField()

class CandidateResultSerializer(serializers.Serializer):
    candidate_id = serializers.UUIDField()
    full_name = serializers.CharField()
    photo = serializers.CharField(allow_null=True)
    photo_url = serializers.CharField(allow_blank=True)
    faculty = serializers.CharField()
    course = serializers.IntegerField()
    position = serializers.CharField()
    votes = serializers.IntegerField()
    percent = serializers.FloatField()

class ElectionResultsSerializer(serializers.Serializer):
    election_id = serializers.UUIDField()
    election_title = serializers.CharField()
    total_eligible = serializers.IntegerField()
    total_voted = serializers.IntegerField()
    turnout_percent = serializers.FloatField()
    candidates = CandidateResultSerializer(many=True)
