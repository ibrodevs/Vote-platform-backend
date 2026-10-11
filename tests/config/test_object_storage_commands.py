import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


class ObjectStorageCommandTest(SimpleTestCase):
    @override_settings(AWS_STORAGE_BUCKET_NAME='')
    def test_smoke_check_requires_object_storage(self):
        with self.assertRaises(CommandError):
            call_command('check_object_storage')

    @override_settings(AWS_STORAGE_BUCKET_NAME='')
    def test_media_migration_requires_object_storage(self):
        with self.assertRaises(CommandError):
            call_command('migrate_local_media_to_object_storage', '--dry-run')

    def test_media_migration_dry_run_does_not_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'students' / 'photos').mkdir(parents=True)
            (root / 'students' / 'photos' / 'student.jpg').write_bytes(b'fake-image')

            fake_storage = mock.Mock()
            fake_storage.exists.return_value = False

            with override_settings(
                AWS_STORAGE_BUCKET_NAME='vote-media',
                MEDIA_ROOT=root,
            ), mock.patch(
                'apps.core.management.commands.migrate_local_media_to_object_storage.default_storage',
                fake_storage,
            ):
                call_command('migrate_local_media_to_object_storage', '--dry-run')

            fake_storage.exists.assert_called_once_with('students/photos/student.jpg')
            fake_storage.save.assert_not_called()
