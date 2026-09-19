from django.urls import path
from .views import (
    PublicNewsListView, PublicRecentNewsView, PublicNewsDetailView
)

urlpatterns = [
    path('', PublicNewsListView.as_view(), name='public_news_list'),
    path('recent/', PublicRecentNewsView.as_view(), name='public_recent_news'),
    path('<uuid:pk>/', PublicNewsDetailView.as_view(), name='public_news_detail'),
]
