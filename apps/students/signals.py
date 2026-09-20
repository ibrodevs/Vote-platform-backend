"""Сигналы поддержания консистентности аутентификации.

ПОЧЕМУ СИГНАЛЫ, А НЕ ЯВНЫЕ ВЫЗОВЫ
---------------------------------
Студентов правят как минимум из трёх мест: DRF-сериализатор админского API,
Django-админка и shell/management-команды. Явный вызов отзыва в одном из них
оставил бы остальные дырявыми, а именно через них чаще всего и деактивируют
студента.

ЧЕГО СИГНАЛЫ НЕ ПОКРЫВАЮТ
-------------------------
`Student.objects.filter(...).update(...)` сигналы не шлёт — это особенность
Django, а не упущение. Для массовых операций нужно вызывать
`services_auth.revoke_student_tokens` явно.

Сам инкремент auth_version живёт в `Student.save()`, а не здесь: сигнал
не может расширить `update_fields` вызывающего save(), поэтому при
`save(update_fields=['is_active'])` новая версия не попала бы в UPDATE.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Student
from .services_auth import invalidate_principal

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Student, dispatch_uid="student_principal_invalidate")
def invalidate_principal_on_save(sender, instance, **kwargs):
    """Любое изменение студента делает кэшированную личность устаревшей."""
    invalidate_principal(instance.pk)
