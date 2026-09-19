from django.urls import path
from .views import PublicFAQListView

urlpatterns = [
    path('', PublicFAQListView.as_view(), name='public_faqs_list'),
]
