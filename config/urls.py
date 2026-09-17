from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin-django/', admin.site.urls),

    # Version 1 API
    path('api/v1/auth/', include('apps.accounts.urls')),
    path('api/v1/auth/student/', include('apps.students.urls_auth')),
    path('api/v1/students/auth/', include('apps.students.urls_auth')),
    path('api/v1/universities/', include('apps.universities.urls_public')),
    path('api/v1/admin/universities/', include('apps.universities.urls_admin')),
    path('api/v1/admin/students/', include('apps.students.urls_admin')),
    path('api/v1/admin/upload-batches/', include('apps.students.urls_batches')),
    path('api/v1/admin/elections/', include('apps.elections.urls_admin')),
    path('api/v1/admin/candidates/', include('apps.candidates.urls_admin')),
    path('api/v1/elections/', include('apps.elections.urls_student')),
    path('api/v1/voting/', include('apps.voting.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
