from rest_framework import serializers
from .models import NewsArticle, FAQItem, NewsCategory

class NewsArticleSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    effective_image = serializers.SerializerMethodField()
    author = serializers.SerializerMethodField()

    class Meta:
        model = NewsArticle
        fields = [
            'id', 'title', 'title_ky', 'summary', 'summary_ky',
            'content', 'content_ky', 'image', 'image_url', 'effective_image',
            'category', 'category_display', 'is_published', 'published_at',
            'views', 'author_name', 'author', 'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']

    def get_effective_image(self, obj) -> str:
        request = self.context.get('request')
        if obj.image:
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return obj.image_url or ''

    def get_author(self, obj) -> str:
        if obj.created_by and obj.created_by.full_name:
            return obj.created_by.full_name
        return obj.author_name or 'Пресс-служба Dobush.kg'

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get('request')
        if instance.image:
            if request:
                ret['image'] = request.build_absolute_uri(instance.image.url)
            else:
                ret['image'] = instance.image.url
        else:
            ret['image'] = instance.image_url or ''
        return ret

class FAQItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQItem
        fields = [
            'id', 'question', 'question_ky', 'answer', 'answer_ky',
            'order', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
