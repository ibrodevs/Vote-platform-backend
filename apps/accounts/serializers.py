from rest_framework import serializers
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from .models import AdminUser, AdminActionLog
from apps.universities.models import University

class UniversityShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = University
        fields = ['id', 'name', 'name_ky', 'code', 'is_active']

class AdminUserSerializer(serializers.ModelSerializer):
    university_details = UniversityShortSerializer(source='university', read_only=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = AdminUser
        fields = [
            'id', 'email', 'full_name', 'role', 'university', 'password',
            'university_details', 'is_active', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']

    def to_internal_value(self, data):
        data = data.copy() if hasattr(data, 'copy') else dict(data)
        if 'university_id' in data and not data.get('university'):
            data['university'] = data['university_id']
        return super().to_internal_value(data)

    def validate(self, attrs):
        role = attrs.get('role', getattr(self.instance, 'role', None))
        university = attrs.get('university', getattr(self.instance, 'university', None))
        if role in [AdminUser.Role.UNIVERSITY_ADMIN, AdminUser.Role.OBSERVER] and not university:
            raise serializers.ValidationError({"university": "Укажите университет для сотрудника"})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = AdminUser(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        if password:
            instance.set_password(password)
        instance.save()
        return instance

class AdminLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        user = authenticate(email=email, password=password)
        if not user:
            raise serializers.ValidationError({"detail": "Неверный email или пароль"})
        if not user.is_active:
            raise serializers.ValidationError({"detail": "Учетная запись администратора деактивирована"})

        refresh = RefreshToken.for_user(user)
        refresh['role'] = user.role
        refresh['university_id'] = str(user.university_id) if user.university_id else None

        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': AdminUserSerializer(user).data
        }

class AdminActionLogSerializer(serializers.ModelSerializer):
    admin_email = serializers.EmailField(source='admin.email', read_only=True)
    admin_name = serializers.CharField(source='admin.full_name', read_only=True)

    class Meta:
        model = AdminActionLog
        fields = ['id', 'admin', 'admin_email', 'admin_name', 'action', 'target_type', 'target_id', 'details', 'ip_address', 'created_at']
        read_only_fields = fields
