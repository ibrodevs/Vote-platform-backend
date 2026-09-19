from django.urls import path
from .views import PublicStaticPageDetailView

urlpatterns = [
    path('<slug:slug>/', PublicStaticPageDetailView.as_view(), name='public_static_page_detail'),
]
