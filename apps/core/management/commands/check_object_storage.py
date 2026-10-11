"""Проверяет реальную запись/чтение/удаление media в S3-compatible storage.

Команда намеренно не принимает ключи аргументами: секреты должны приходить
только из environment/.env. Проверка создаёт временный объект, читает его и
всегда пытается удалить в finally.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Проверить доступ Django к настроенному S3-compatible media storage"

    def handle(self, *args, **options):
        bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "")
        if not bucket:
            raise CommandError(
                "AWS_STORAGE_BUCKET_NAME не задан: default storage остаётся локальным."
            )

        expected = b"vote-platform-object-storage-ok\n"
        requested_name = f"_healthchecks/{uuid.uuid4().hex}.txt"
        saved_name = None

        self.stdout.write(f"bucket={bucket}")
        self.stdout.write(f"storage={default_storage.__class__.__module__}.{default_storage.__class__.__name__}")

        try:
            saved_name = default_storage.save(requested_name, ContentFile(expected))

            if not default_storage.exists(saved_name):
                raise CommandError("Объект был загружен, но storage.exists() вернул False.")

            with default_storage.open(saved_name, "rb") as fh:
                received = fh.read()

            if received != expected:
                raise CommandError(
                    f"Содержимое объекта после чтения не совпало: {len(received)} bytes."
                )

            url = default_storage.url(saved_name)
            if not url.startswith(("http://", "https://")):
                raise CommandError(f"Storage вернул не абсолютный media URL: {url!r}")

            self.stdout.write(self.style.SUCCESS("OBJECT STORAGE READ/WRITE OK"))
            self.stdout.write(f"url={url}")
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(
                f"Object Storage check failed: {exc.__class__.__name__}: {exc}"
            ) from exc
        finally:
            if saved_name:
                try:
                    default_storage.delete(saved_name)
                except Exception as exc:  # cleanup не должен скрывать основную ошибку
                    self.stderr.write(
                        self.style.WARNING(
                            f"Не удалось удалить временный объект {saved_name}: {exc}"
                        )
                    )
