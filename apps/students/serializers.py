from rest_framework import serializers
from .models import Student, UploadBatch, StudentAuthSession

class StudentSerializer(serializers.ModelSerializer):
    university_name = serializers.CharField(source='university.name', read_only=True)
    university_code = serializers.CharField(source='university.code', read_only=True)

    class Meta:
        model = Student
        fields = [
            'id', 'university', 'university_name', 'university_code',
            'student_id', 'full_name', 'phone_number', 'email',
            'faculty', 'group', 'course', 'is_active', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']

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
    course = serializers.IntegerField(min_value=1, max_value=6)
    group = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=6, write_only=True)

class StudentPasswordLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
