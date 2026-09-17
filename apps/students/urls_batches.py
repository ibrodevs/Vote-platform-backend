from django.urls import path
from .views import AdminUploadBatchStatusView

urlpatterns = [
    path('<uuid:pk>/status/', AdminUploadBatchStatusView.as_view(), name='admin_upload_batch_status'),
]
