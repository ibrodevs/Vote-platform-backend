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

    # Раньше здесь были obj.vote_records.exists() / .count() / .order_by().
    # Вьюха делала prefetch_related('vote_records'), но пользы от него не было:
    # exists() и order_by() prefetch-кэш НЕ используют и всегда идут в базу.
    # Получалось три запроса на каждого студента списка — 44 SQL на 20 студентов.
    # Теперь всё считает база одной агрегацией (ТЗ п.26).
    VOTES_COUNT_ANNOTATION = 'votes_count_annotated'
    LAST_VOTED_ANNOTATION = 'last_voted_at_annotated'

    def get_has_voted(self, obj) -> bool:
        return self.get_votes_count(obj) > 0

    def get_votes_count(self, obj) -> int:
        annotated = getattr(obj, self.VOTES_COUNT_ANNOTATION, None)
        if annotated is not None:
            return annotated
        return obj.vote_records.count()

    def get_voted_at(self, obj):
        if hasattr(obj, self.LAST_VOTED_ANNOTATION):
            latest = getattr(obj, self.LAST_VOTED_ANNOTATION)
            return latest.isoformat() if latest else None
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
