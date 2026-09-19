from django.urls import path
from .views import (
    AdminNewsListCreateView, AdminNewsDetailView,
    AdminFAQListCreateView, AdminFAQDetailView
)

urlpatterns = [
    # News admin
    path('news/', AdminNewsListCreateView.as_view(), name='admin_news_list_create'),
    path('news/<uuid:pk>/', AdminNewsDetailView.as_view(), name='admin_news_detail'),

    # FAQ admin (Superadmin only)
    path('faqs/', AdminFAQListCreateView.as_view(), name='admin_faqs_list_create'),
    path('faqs/<uuid:pk>/', AdminFAQDetailView.as_view(), name='admin_faqs_detail'),
]
