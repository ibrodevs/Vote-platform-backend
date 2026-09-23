"""Проверки готовности к нескольким репликам приложения (ТЗ п.99).

Падение одной ноды не должно затрагивать пользователей остальных, а для
этого в процессе приложения не должно жить состояние. Две настройки
нарушают это молча: локальный кэш и локальные медиафайлы.
"""
import os
from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.core.system_checks import ALL_CHECKS, check_media_storage, check_shared_cache

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
DUMMY = {'default': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'}}
REDIS = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache'}}


class SharedCacheCheckTest(SimpleTestCase):
    @override_settings(CACHES=LOCMEM)
    def test_locmem_is_rejected(self):
        """У каждой реплики был бы свой кэш и свои счётчики троттлинга."""
        result = check_shared_cache()
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 'cache_not_shared')

    @override_settings(CACHES=DUMMY)
    def test_disabled_cache_is_rejected(self):
        result = check_shared_cache()
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 'cache_disabled')

    @override_settings(CACHES=REDIS)
    def test_redis_passes(self):
        self.assertTrue(check_shared_cache().ok)


class MediaStorageCheckTest(SimpleTestCase):
    @override_settings(AWS_STORAGE_BUCKET_NAME='')
    def test_local_media_is_rejected_by_default(self):
        with mock.patch.dict(os.environ, {'DJANGO_MEDIA_SHARED': 'False'}):
            result = check_media_storage()
        self.assertFalse(result.ok)
        self.assertEqual(result.code, 'media_storage_local')
        # Подсказка обязана назвать оба выхода.
        self.assertIn('AWS_STORAGE_BUCKET_NAME', result.hint)
        self.assertIn('DJANGO_MEDIA_SHARED', result.hint)

    @override_settings(AWS_STORAGE_BUCKET_NAME='vote-media')
    def test_object_storage_passes(self):
        self.assertTrue(check_media_storage().ok)

    @override_settings(AWS_STORAGE_BUCKET_NAME='')
    def test_shared_filesystem_passes_when_declared(self):
        """Общий сетевой диск допустим, но Django не отличит его от локального."""
        with mock.patch.dict(os.environ, {'DJANGO_MEDIA_SHARED': 'True'}):
            self.assertTrue(check_media_storage().ok)


class ChecksAreRegisteredTest(SimpleTestCase):
    def test_both_checks_run_before_deploy(self):
        self.assertIn(check_shared_cache, ALL_CHECKS)
        self.assertIn(check_media_storage, ALL_CHECKS)
