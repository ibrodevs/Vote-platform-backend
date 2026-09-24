from rest_framework import serializers
from .models import University, Faculty

class FacultySerializer(serializers.ModelSerializer):
    class Meta:
        model = Faculty
        fields = ['id', 'name', 'name_ky', 'code']
        read_only_fields = ['id']

class UniversitySerializer(serializers.ModelSerializer):
    students_count = serializers.SerializerMethodField()
    active_elections_count = serializers.SerializerMethodField()
    faculties = FacultySerializer(many=True, read_only=True)
    faculties_input = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        write_only=True
    )

    class Meta:
        model = University
        fields = [
            'id', 'name', 'name_ky', 'code', 'logo', 'is_active', 'is_registration_open',
            'created_at', 'students_count', 'active_elections_count',
            'faculties', 'faculties_input'
        ]
        read_only_fields = ['id', 'created_at']

    # Два условных счётчика считаются одной агрегацией во вьюхе, а не двумя
    # запросами на каждый университет списка (ТЗ п.26).
    STUDENTS_COUNT_ANNOTATION = 'students_count_annotated'
    ACTIVE_ELECTIONS_ANNOTATION = 'active_elections_count_annotated'

    def get_students_count(self, obj):
        annotated = getattr(obj, self.STUDENTS_COUNT_ANNOTATION, None)
        if annotated is not None:
            return annotated
        return obj.students.count()

    def get_active_elections_count(self, obj):
        annotated = getattr(obj, self.ACTIVE_ELECTIONS_ANNOTATION, None)
        if annotated is not None:
            return annotated
        return obj.elections.filter(status='active').count()

    def create(self, validated_data):
        faculties_input = validated_data.pop('faculties_input', None)
        university = super().create(validated_data)
        if faculties_input:
            for fac_name in faculties_input:
                name_clean = fac_name.strip()
                if name_clean:
                    Faculty.objects.create(university=university, name=name_clean)
        return university

    def update(self, instance, validated_data):
        faculties_input = validated_data.pop('faculties_input', None)
        university = super().update(instance, validated_data)
        if faculties_input is not None:
            existing_faculties = {f.name.strip().lower(): f for f in university.faculties.all()}
            new_names = [f.strip() for f in faculties_input if f.strip()]
            new_names_lower = {n.lower() for n in new_names}

            for f_name_lower, f_obj in existing_faculties.items():
                if f_name_lower not in new_names_lower:
                    f_obj.delete()

            for n in new_names:
                if n.lower() not in existing_faculties:
                    Faculty.objects.create(university=university, name=n)
        return university

class UniversityPublicSerializer(serializers.ModelSerializer):
    faculties = FacultySerializer(many=True, read_only=True)

    class Meta:
        model = University
        fields = ['id', 'name', 'name_ky', 'code', 'logo', 'is_active', 'is_registration_open', 'faculties']

class UniversityShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = University
        fields = ['id', 'name', 'name_ky', 'code', 'is_active', 'is_registration_open']

