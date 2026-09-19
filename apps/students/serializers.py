import os
from rest_framework import serializers
from .models import Student, UploadBatch, StudentAuthSession

class StudentSerializer(serializers.ModelSerializer):
    university_name = serializers.CharField(source='university.name', read_only=True)
    university_code = serializers.CharField(source='university.code', read_only=True)
    has_voted = serializers.SerializerMethodField()
    voted_at = serializers.SerializerMethodField()
    votes_count = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            'id', 'university', 'university_name', 'university_code',
            'student_id', 'full_name', 'phone_number', 'email', 'photo',
            'faculty', 'group', 'course', 'is_active',
            'has_voted', 'voted_at', 'votes_count', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def get_has_voted(self, obj) -> bool:
        # Check if pre-annotated or query vote_records
        if hasattr(obj, 'prefetched_vote_records'):
            return len(obj.prefetched_vote_records) > 0
        return obj.vote_records.exists()

    def get_votes_count(self, obj) -> int:
        if hasattr(obj, 'prefetched_vote_records'):
            return len(obj.prefetched_vote_records)
        return obj.vote_records.count()

    def get_voted_at(self, obj):
        if hasattr(obj, 'prefetched_vote_records') and obj.prefetched_vote_records:
            latest = sorted(obj.prefetched_vote_records, key=lambda r: r.voted_at, reverse=True)[0]
            return latest.voted_at.isoformat()
        latest = obj.vote_records.order_by('-voted_at').first()
        return latest.voted_at.isoformat() if latest else None

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get('request')
        if instance.photo:
            try:
                url = instance.photo.url
                if request is not None:
                    ret['photo'] = request.build_absolute_uri(url)
                else:
                    backend_url = os.getenv('BACKEND_URL', '').rstrip('/')
                    ret['photo'] = f"{backend_url}{url}" if backend_url else url
            except Exception:
                ret['photo'] = None
        else:
            ret['photo'] = None
        return ret

class UploadBatchSerializer(serializers.ModelSerializer):
    university_name = serializers.CharField(source='university.name', read_only=True)
    uploaded_by_name = serializers.CharField(source='uploaded_by.full_name', read_only=True, default='')

    class Meta:
        model = UploadBatch
        fields = [
            'id', 'university', 'university_name', 'uploaded_by', 'uploaded_by_name',
            'file_name', 'total_rows', 'success_count', 'error_count',
            'errors_detail', 'status', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'status', 'total_rows', 'success_count', 'error_count', 'errors_detail']

class StudentIdentifySerializer(serializers.Serializer):
    university_code = serializers.CharField(max_length=50)
    student_id = serializers.CharField(max_length=100)
    phone_number = serializers.CharField(max_length=50)

class StudentVerifySerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    code = serializers.CharField(max_length=10)

class StudentRegisterSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255)
    university_id = serializers.UUIDField()
    faculty = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    course = serializers.IntegerField(min_value=1, max_value=6)
    group = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=6, write_only=True)

class StudentPasswordLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
