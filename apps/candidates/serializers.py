import os
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

    def validate_short_bio(self, value):
        if value and len(value.strip()) > 100:
            raise serializers.ValidationError("Краткая биография не должна превышать 100 символов.")
        return value

    def validate_program(self, value):
        if value and len(value.strip()) > 100:
            raise serializers.ValidationError("Предвыборная программа не должна превышать 100 символов.")
        return value

    def create(self, validated_data):
        if 'election' in validated_data and 'university' not in validated_data:
            validated_data['university'] = validated_data['election'].university
        return super().create(validated_data)

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
                ret['photo'] = instance.photo_url or None
        elif instance.photo_url:
            ret['photo'] = instance.photo_url
        return ret

class CandidatePublicSerializer(serializers.ModelSerializer):
    university_name = serializers.CharField(source='university.name', read_only=True)
    election_title = serializers.CharField(source='election.title', read_only=True)

    class Meta:
        model = Candidate
        fields = [
            'id', 'election', 'election_title', 'university', 'university_name',
            'full_name', 'photo', 'photo_url', 'faculty', 'course',
            'position', 'short_bio', 'program', 'order'
        ]

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
                ret['photo'] = instance.photo_url or None
        elif instance.photo_url:
            ret['photo'] = instance.photo_url
        return ret

class CandidateReorderSerializer(serializers.Serializer):
    ordered_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False
    )
