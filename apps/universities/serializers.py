from rest_framework import serializers
from .models import University

class UniversitySerializer(serializers.ModelSerializer):
    students_count = serializers.SerializerMethodField()
    active_elections_count = serializers.SerializerMethodField()

    class Meta:
        model = University
        fields = [
            'id', 'name', 'name_ky', 'code', 'logo', 'is_active',
            'created_at', 'students_count', 'active_elections_count'
        ]
        read_only_fields = ['id', 'created_at']

    def get_students_count(self, obj):
        return obj.students.count()

    def get_active_elections_count(self, obj):
        return obj.elections.filter(status='active').count()

class UniversityPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = University
        fields = ['id', 'name', 'name_ky', 'code', 'logo', 'is_active']

class UniversityShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = University
        fields = ['id', 'name', 'name_ky', 'code', 'is_active']

