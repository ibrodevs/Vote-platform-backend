import uuid
from django.db import models
from django.utils import timezone
from apps.core.models import TimeStampedUUIDModel
from apps.accounts.models import AdminUser

class NewsCategory(models.TextChoices):
    OFFICIAL = 'official', 'Официально'
    ELECTIONS = 'elections', 'Выборы'
    TECH = 'tech', 'Технологии'
    STUDENTS = 'students', 'Студенчество'

class NewsArticle(TimeStampedUUIDModel):
    title = models.CharField(max_length=255, verbose_name="Заголовок (RU)")
    title_ky = models.CharField(max_length=255, blank=True, default="", verbose_name="Заголовок (KY)")
    summary = models.TextField(blank=True, default="", verbose_name="Краткое описание (RU)")
    summary_ky = models.TextField(blank=True, default="", verbose_name="Краткое описание (KY)")
    content = models.TextField(verbose_name="Полное содержание (RU)")
    content_ky = models.TextField(blank=True, default="", verbose_name="Полное содержание (KY)")
    image = models.ImageField(upload_to="news/", null=True, blank=True, verbose_name="Изображение")
    image_url = models.URLField(blank=True, default="", verbose_name="URL изображения")
    category = models.CharField(
        max_length=50,
        choices=NewsCategory.choices,
        default=NewsCategory.OFFICIAL,
        verbose_name="Категория"
    )
    is_published = models.BooleanField(default=True, verbose_name="Опубликовано")
    published_at = models.DateTimeField(default=timezone.now, verbose_name="Дата публикации")
    views = models.PositiveIntegerField(default=0, verbose_name="Просмотры")
    author_name = models.CharField(max_length=100, default="Пресс-служба Dobush.kg", verbose_name="Имя автора")
    created_by = models.ForeignKey(
        AdminUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='news_articles',
        verbose_name="Создатель"
    )

    class Meta:
        verbose_name = "Новость"
        verbose_name_plural = "Новости"
        ordering = ['-published_at', '-created_at']

    def __str__(self):
        return self.title

class FAQItem(TimeStampedUUIDModel):
    question = models.CharField(max_length=255, verbose_name="Вопрос (RU)")
    question_ky = models.CharField(max_length=255, blank=True, default="", verbose_name="Вопрос (KY)")
    answer = models.TextField(verbose_name="Ответ (RU)")
    answer_ky = models.TextField(blank=True, default="", verbose_name="Ответ (KY)")
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок сортировки")
    is_active = models.BooleanField(default=True, verbose_name="Активен")

    class Meta:
        verbose_name = "Вопрос-ответ (FAQ)"
        verbose_name_plural = "Вопросы и ответы (FAQ)"
        ordering = ['order', 'created_at']

    def __str__(self):
        return self.question
