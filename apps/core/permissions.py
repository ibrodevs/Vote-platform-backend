from rest_framework.permissions import BasePermission

class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return getattr(user, 'role', None) == 'super_admin' or user.is_superuser

class IsAdminUserWithRole(BasePermission):
    """Allows access to super_admin and university_admin."""
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return getattr(user, 'role', None) in ['super_admin', 'university_admin'] or user.is_superuser

class IsUniversityAdmin(IsAdminUserWithRole):
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if getattr(user, 'role', None) == 'super_admin' or user.is_superuser:
            return True
        # For university_admin: must match the university
        if hasattr(obj, 'university'):
            return obj.university == user.university
        if hasattr(obj, 'university_id'):
            return str(obj.university_id) == str(getattr(user, 'university_id', ''))
        # If obj itself is University
        return obj == user.university

class IsStudentAuthenticated(BasePermission):
    """Allows access only to authenticated students."""
    def has_permission(self, request, view):
        return bool(request.user and getattr(request.user, 'is_student', False))
