# Hetzner Object Storage for Django media

The backend already uses `django-storages` and automatically switches the Django `default` file storage to S3 when `AWS_STORAGE_BUCKET_NAME` is set. Static files stay on WhiteNoise/Nginx; only user-uploaded media moves to Object Storage.

## 1. Bucket requirements

Use a Hetzner Object Storage bucket in the same location as the application where possible (for the current production server: `hel1`).

For public candidate/student/university/news images, set the bucket visibility to **Public**. The backend intentionally uses permanent unsigned media URLs (`AWS_QUERYSTRING_AUTH=False`), so the bucket must allow anonymous `GET`. Write/delete operations still require the S3 credentials.

Do not commit access/secret keys to GitHub. Keep them only in the production `.env` (mode `600`).

## 2. Production environment

For a bucket named `YOUR_BUCKET` in Helsinki:

```env
DJANGO_MEDIA_SHARED=False
AWS_STORAGE_BUCKET_NAME=YOUR_BUCKET
AWS_S3_ENDPOINT_URL=https://hel1.your-objectstorage.com
AWS_S3_CUSTOM_DOMAIN=YOUR_BUCKET.hel1.your-objectstorage.com
AWS_S3_REGION_NAME=hel1
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY
```

`AWS_S3_CUSTOM_DOMAIN` is a hostname only — do not include `https://`.

## 3. Safe rollout

From `/home/deployer/projects/Vote-platform-backend`:

```bash
cp .env ".env.backup.$(date +%Y%m%d-%H%M%S)"
chmod 600 .env
```

Update the S3 variables in `.env`, then build the new application image without restarting production yet:

```bash
docker compose -f docker-compose.prod.yml build app celery-default celery-heavy
```

Run a real read/write/delete smoke check using a one-off application container. It reads the new `.env` but does not replace the running web container:

```bash
docker compose -f docker-compose.prod.yml run --rm --no-deps app \
  python manage.py check_object_storage
```

Expected result:

```text
OBJECT STORAGE READ/WRITE OK
url=https://YOUR_BUCKET.hel1.your-objectstorage.com/...
```

## 4. Copy existing local media before switching web traffic

The production compose file still mounts the old `media` volume. Keep it during the migration so rollback remains possible.

First preview:

```bash
docker compose -f docker-compose.prod.yml run --rm --no-deps app \
  python manage.py migrate_local_media_to_object_storage --dry-run
```

Then copy:

```bash
docker compose -f docker-compose.prod.yml run --rm --no-deps app \
  python manage.py migrate_local_media_to_object_storage
```

The command never deletes local files. Existing objects in the bucket are skipped by default; use `--force` only when an intentional overwrite is required.

## 5. Switch the running processes

Recreate only processes that load Django settings:

```bash
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate \
  app celery-default celery-heavy
```

Nginx does not need to serve the new media. API serializers receive absolute Object Storage URLs from Django and return those URLs to the frontend.

Verify readiness:

```bash
curl -fsS https://api.dobush.kg/health/ready && echo
```

Then upload one harmless image through the normal admin/API flow and confirm that its returned URL points to:

```text
https://YOUR_BUCKET.hel1.your-objectstorage.com/...
```

## 6. Rollback

If Object Storage access fails, restore the previous `.env` and recreate `app`/Celery again. The migration command leaves the original local media volume untouched, so rollback does not lose existing files.

## Notes

- PostgreSQL stores only file names/paths; binary media is stored in Object Storage after the switch.
- Media delivery no longer consumes Gunicorn or Nginx application capacity.
- Static assets remain local/WhiteNoise by design.
- Keep the old media volume until the Object Storage rollout has been verified and backed up.
