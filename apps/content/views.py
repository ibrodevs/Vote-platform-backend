from rest_framework import generics, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import F

from .models import NewsArticle, FAQItem
from .serializers import NewsArticleSerializer, FAQItemSerializer
from apps.core.permissions import IsSuperAdmin, IsAdminUserWithRole
from apps.accounts.models import AdminActionLog

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')

class CanManageNews(permissions.BasePermission):
    """
    Super Admin has full access (CRUD).
    Staff (university_admin, observer) can create and read news, and update their own.
    Deletion is restricted to Super Admin.
    """
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if getattr(user, 'role', None) == 'super_admin' or user.is_superuser:
            return True
        # Staff can list and create
        if request.method in permissions.SAFE_METHODS or request.method == 'POST':
            return True
        # For PUT/PATCH/DELETE, object-level check or method check
        if request.method == 'DELETE':
            return False
        return True

    def has_object_permission(self, request, view, obj):
        user = request.user
        if getattr(user, 'role', None) == 'super_admin' or user.is_superuser:
            return True
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.method == 'DELETE':
            return False
        # Staff can update their own news
        return obj.created_by == user

# --- Admin News Views ---

class AdminNewsListCreateView(generics.ListCreateAPIView):
    permission_classes = [CanManageNews]
    serializer_class = NewsArticleSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['category', 'is_published']
    search_fields = ['title', 'title_ky', 'summary', 'content']
    ordering_fields = ['published_at', 'created_at', 'views', 'title']
    ordering = ['-published_at']

    def get_queryset(self):
        return NewsArticle.objects.all().select_related('created_by')

    def perform_create(self, serializer):
        article = serializer.save(created_by=self.request.user)
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="create_news",
            target_type="news",
            target_id=str(article.id),
            details={"title": article.title, "category": article.category},
            ip_address=get_client_ip(self.request)
        )

class AdminNewsDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [CanManageNews]
    serializer_class = NewsArticleSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    queryset = NewsArticle.objects.all().select_related('created_by')

    def perform_update(self, serializer):
        article = serializer.save()
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="update_news",
            target_type="news",
            target_id=str(article.id),
            details={"title": article.title, "is_published": article.is_published},
            ip_address=get_client_ip(self.request)
        )

    def perform_destroy(self, instance):
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="delete_news",
            target_type="news",
            target_id=str(instance.id),
            details={"title": instance.title},
            ip_address=get_client_ip(self.request)
        )
        instance.delete()

# --- Admin FAQ Views (Super Admin Only) ---

class AdminFAQListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = FAQItemSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['question', 'question_ky', 'answer', 'answer_ky']
    ordering_fields = ['order', 'created_at']
    ordering = ['order', 'created_at']
    queryset = FAQItem.objects.all()

    def perform_create(self, serializer):
        faq = serializer.save()
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="create_faq",
            target_type="faq",
            target_id=str(faq.id),
            details={"question": faq.question},
            ip_address=get_client_ip(self.request)
        )

class AdminFAQDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsSuperAdmin]
    serializer_class = FAQItemSerializer
    queryset = FAQItem.objects.all()

    def perform_update(self, serializer):
        faq = serializer.save()
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="update_faq",
            target_type="faq",
            target_id=str(faq.id),
            details={"question": faq.question, "is_active": faq.is_active},
            ip_address=get_client_ip(self.request)
        )

    def perform_destroy(self, instance):
        AdminActionLog.objects.create(
            admin=self.request.user,
            action="delete_faq",
            target_type="faq",
            target_id=str(instance.id),
            details={"question": instance.question},
            ip_address=get_client_ip(self.request)
        )
        instance.delete()

# --- Public Views ---

class PublicNewsListView(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = NewsArticleSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['category']
    search_fields = ['title', 'title_ky', 'summary', 'summary_ky', 'content', 'content_ky']
    ordering_fields = ['published_at', 'views']
    ordering = ['-published_at']

    def get_queryset(self):
        return NewsArticle.objects.filter(is_published=True).select_related('created_by')

class PublicRecentNewsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        articles = NewsArticle.objects.filter(is_published=True).select_related('created_by').order_by('-published_at')[:3]
        serializer = NewsArticleSerializer(articles, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

class PublicNewsDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = NewsArticleSerializer
    queryset = NewsArticle.objects.filter(is_published=True).select_related('created_by')

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        NewsArticle.objects.filter(id=instance.id).update(views=F('views') + 1)
        instance.refresh_from_db()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

class PublicFAQListView(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = FAQItemSerializer
    pagination_class = None

    def get_queryset(self):
        return FAQItem.objects.filter(is_active=True).order_by('order', 'created_at')
