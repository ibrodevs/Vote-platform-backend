from rest_framework.permissions import BasePermission, SAFE_METHODS

class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return getattr(user, 'role', None) == 'super_admin' or user.is_superuser

class IsAdminUserWithRole(BasePermission):
    """
    Allows full access to super_admin and university_admin.
    Allows read-only access (SAFE_METHODS) to observer.
    """
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        role = getattr(user, 'role', None)
        if role in ['super_admin', 'university_admin']:
            return True
        if role == 'observer':
            return request.method in SAFE_METHODS
        return False

class IsNotObserver(BasePermission):
    """Denies access to observer role (read-only university staff)."""
    message = "У вашей учетной записи есть права только для просмотра. Внесение изменений запрещено."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return getattr(user, 'role', None) != 'observer'

class IsUniversityAdmin(IsAdminUserWithRole):
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if getattr(user, 'role', None) == 'super_admin' or user.is_superuser:
            return True
        # Observers can only view
        if getattr(user, 'role', None) == 'observer' and request.method not in SAFE_METHODS:
            return False
        # For university_admin & observer: must match the university
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
