"""Копирует существующие локальные MEDIA_ROOT файлы в default object storage.

Команда ничего не удаляет с локального диска. Это позволяет выполнить перенос
до переключения production web-процессов и сохранить простой rollback.
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Скопировать локальный MEDIA_ROOT в настроенный S3-compatible default storage"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать, что будет загружено, ничего не меняя в Object Storage.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Перезаписать уже существующие объекты с тем же ключом.",
        )

    def handle(self, *args, **options):
        bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "")
        if not bucket:
            raise CommandError(
                "AWS_STORAGE_BUCKET_NAME не задан: object storage не включён."
            )

        root = Path(settings.MEDIA_ROOT)
        if not root.exists():
            self.stdout.write(self.style.SUCCESS(f"MEDIA_ROOT отсутствует: {root}; переносить нечего."))
            return

        files = sorted(path for path in root.rglob("*") if path.is_file())
        if not files:
            self.stdout.write(self.style.SUCCESS(f"MEDIA_ROOT пуст: {root}; переносить нечего."))
            return

        dry_run = options["dry_run"]
        force = options["force"]
        uploaded = 0
        skipped = 0
        failed = 0
        total_bytes = 0

        self.stdout.write(f"source={root}")
        self.stdout.write(f"bucket={bucket}")
        self.stdout.write(f"files={len(files)}")
        self.stdout.write(f"dry_run={dry_run} force={force}")

        for path in files:
            key = path.relative_to(root).as_posix()
            size = path.stat().st_size

            try:
                exists = default_storage.exists(key)
                if exists and not force:
                    skipped += 1
                    self.stdout.write(f"SKIP {key} ({size} bytes)")
                    continue

                if dry_run:
                    uploaded += 1
                    total_bytes += size
                    self.stdout.write(f"WOULD_UPLOAD {key} ({size} bytes)")
                    continue

                if exists and force:
                    default_storage.delete(key)

                with path.open("rb") as fh:
                    saved_name = default_storage.save(key, File(fh, name=path.name))

                if saved_name != key:
                    raise RuntimeError(
                        f"storage изменил ключ {key!r} -> {saved_name!r}; перенос остановлен для этого файла"
                    )
                if not default_storage.exists(key):
                    raise RuntimeError("объект не найден после загрузки")

                remote_size = default_storage.size(key)
                if remote_size != size:
                    raise RuntimeError(
                        f"размер не совпал: local={size}, remote={remote_size}"
                    )

                uploaded += 1
                total_bytes += size
                self.stdout.write(self.style.SUCCESS(f"UPLOADED {key} ({size} bytes)"))
            except Exception as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f"FAILED {key}: {exc}"))

        self.stdout.write("")
        self.stdout.write(
            f"uploaded={uploaded} skipped={skipped} failed={failed} bytes={total_bytes}"
        )

        if failed:
            raise CommandError(f"Перенос завершён с ошибками: {failed} файл(ов).")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("DRY RUN OK"))
        else:
            self.stdout.write(self.style.SUCCESS("MEDIA MIGRATION OK"))
