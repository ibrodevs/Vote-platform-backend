from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.http import JsonResponse

def api_root(request):
    return JsonResponse({
        'status': 'online',
        'message': 'Dobush.kg API is operational and accepting requests from all origins.',
        'version': '1.0.0',
        'endpoints': {
            'health': '/api/health/',
            'public_universities': '/api/v1/universities/',
            'student_register': '/api/v1/students/auth/register/',
            'student_login': '/api/v1/students/auth/login/',
            'student_profile': '/api/v1/students/auth/me/',
            'admin_login': '/api/v1/auth/login/',
            'django_admin': '/admin-django/',
        }
    })

def health_check(request):
    return JsonResponse({'status': 'healthy', 'service': 'dobush-backend'})

urlpatterns = [
    # Public root & healthcheck
    path('', api_root, name='api-root'),
    path('api/', api_root, name='api-index'),
    path('api/health/', health_check, name='health-check'),

    # Django Admin
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
    path('api/v1/candidates/', include('apps.candidates.urls_public')),
    path('api/v1/elections/', include('apps.elections.urls_student')),
    path('api/v1/voting/', include('apps.voting.urls')),
    path('api/v1/news/', include('apps.content.urls_public')),
    path('api/v1/faqs/', include('apps.content.urls_faqs_public')),
    path('api/v1/pages/', include('apps.content.urls_pages_public')),
    path('api/v1/admin/content/', include('apps.content.urls_admin')),

    # Media and static fallback serving (guarantees candidate photos and static assets always serve on PythonAnywhere)
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATIC_ROOT}),
]

