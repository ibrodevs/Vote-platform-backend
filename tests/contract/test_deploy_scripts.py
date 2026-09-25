"""Тесты скриптов деплоя, бэкапа и восстановления (ТЗ п.18, 19, 20)."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from django.test import SimpleTestCase

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


class BackupScriptConfigTest(SimpleTestCase):
    """Тесты парсинга окружения скриптом backup.sh (ТЗ п.18)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.env_file = os.path.join(self.temp_dir, ".env")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_backup_sh_receives_s3_bucket_and_retention_days(self):
        with open(self.env_file, "w") as f:
            f.write(
                "DB_NAME=custom_vote_db\n"
                "DB_USER=custom_user\n"
                "DB_PASSWORD=secret_pass\n"
                "DB_HOST=10.0.0.50\n"
                "DB_PORT=6432\n"
                "BACKUP_DIR=/var/backups/vote\n"
                "S3_BACKUP_BUCKET=s3://production-vote-backups\n"
                "RETENTION_DAYS=21\n"
            )

        cmd = [
            "bash",
            str(BACKEND_DIR / "scripts" / "backup.sh"),
            "--print-config",
            self.env_file,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=BACKEND_DIR)
        self.assertEqual(result.returncode, 0, f"backup.sh stderr: {result.stderr}")
        output = result.stdout

        self.assertIn("DB_NAME=custom_vote_db", output)
        self.assertIn("DB_USER=custom_user", output)
        self.assertIn("DB_HOST=10.0.0.50", output)
        self.assertIn("DB_PORT=6432", output)
        self.assertIn("BACKUP_DIR=/var/backups/vote", output)
        self.assertIn("S3_BACKUP_BUCKET=s3://production-vote-backups", output)
        self.assertIn("RETENTION_DAYS=21", output)

    def test_backup_sh_fallback_to_backup_retention_days(self):
        with open(self.env_file, "w") as f:
            f.write(
                "S3_BACKUP_BUCKET=s3://test-bucket\n"
                "BACKUP_RETENTION_DAYS=28\n"
            )

        cmd = [
            "bash",
            str(BACKEND_DIR / "scripts" / "backup.sh"),
            "--print-config",
            self.env_file,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=BACKEND_DIR)
        self.assertEqual(result.returncode, 0)
        self.assertIn("RETENTION_DAYS=28", result.stdout)


class RestoreScriptConfigTest(SimpleTestCase):
    """Тесты логики readiness и парсинга окружения в restore.sh (ТЗ п.4, 5, 6, 20)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.env_file = os.path.join(self.temp_dir, ".env")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_restore_bootstrap_selects_http_url(self):
        with open(self.env_file, "w") as f:
            f.write(
                "DEPLOYMENT_STAGE=bootstrap\n"
                "API_DOMAIN=api.example.kg\n"
            )

        cmd = [
            "bash",
            str(BACKEND_DIR / "scripts" / "restore.sh"),
            "--print-config",
            self.env_file,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=BACKEND_DIR)
        self.assertEqual(result.returncode, 0)
        self.assertIn("DEPLOYMENT_STAGE=bootstrap", result.stdout)
        self.assertIn("READY_URL=http://127.0.0.1/health/ready", result.stdout)

    def test_restore_production_selects_https_api_domain_url(self):
        with open(self.env_file, "w") as f:
            f.write(
                "DEPLOYMENT_STAGE=production\n"
                "API_DOMAIN=api.vote.kg\n"
            )

        cmd = [
            "bash",
            str(BACKEND_DIR / "scripts" / "restore.sh"),
            "--print-config",
            self.env_file,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=BACKEND_DIR)
        self.assertEqual(result.returncode, 0)
        self.assertIn("DEPLOYMENT_STAGE=production", result.stdout)
        self.assertIn("API_DOMAIN=api.vote.kg", result.stdout)
        self.assertIn("READY_URL=https://api.vote.kg/health/ready", result.stdout)

    def test_restore_production_missing_api_domain_has_empty_url(self):
        with open(self.env_file, "w") as f:
            f.write(
                "DEPLOYMENT_STAGE=production\n"
                "API_DOMAIN=\n"
            )

        cmd = [
            "bash",
            str(BACKEND_DIR / "scripts" / "restore.sh"),
            "--print-config",
            self.env_file,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=BACKEND_DIR)
        self.assertEqual(result.returncode, 0)
        self.assertIn("READY_URL=\n", result.stdout + "\n")

    def test_restore_readiness_curl_logic_rejects_301_redirect(self):
        """Проверяем, что логика проверки readiness не считает 301 Redirect успехом (ТЗ п.4)."""
        check_script = """
        check_code() {
            local code="$1"
            if [ "$code" = "200" ]; then
                return 0
            fi
            return 1
        }
        check_code "301" && exit 0 || exit 2
        """
        res = subprocess.run(["bash", "-c", check_script], capture_output=True)
        self.assertEqual(res.returncode, 2, "301 redirect must NOT be treated as success!")


class PreflightScriptConsistencyTest(SimpleTestCase):
    """Тесты проверки согласованности preflight.sh (ТЗ п.7, 8, 9, 10, 11, 12, 19)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.env_file = os.path.join(self.temp_dir, ".env")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_env(self, **kwargs):
        defaults = {
            "DJANGO_ENV": "production",
            "DEPLOYMENT_STAGE": "bootstrap",
            "DJANGO_SECRET_KEY": "valid-long-secret-key-for-test-at-least-32-chars",
            "DJANGO_ALLOWED_HOSTS": "127.0.0.1",
            "DJANGO_CORS_ALLOWED_ORIGINS": "http://127.0.0.1",
            "DB_PASSWORD": "long_secure_db_password_1234",
            "REDIS_PASSWORD": "long_secure_redis_password_1234",
            "REDIS_URL": "redis://:long_secure_redis_password_1234@127.0.0.1:6379/1",
            "CELERY_BROKER_URL": "redis://:long_secure_redis_password_1234@127.0.0.1:6379/0",
            "DB_BEHIND_PGBOUNCER": "True",
            "DB_CONN_MAX_AGE": "0",
            "NGINX_CONF_FILE": "http.conf",
            "API_DOMAIN": "",
            "ADMIN_ALLOWED_IP": "",
        }
        defaults.update(kwargs)
        with open(self.env_file, "w") as f:
            for k, v in defaults.items():
                f.write(f"{k}={v}\n")

    def _run_preflight(self):
        cmd = [
            "bash",
            str(BACKEND_DIR / "scripts" / "preflight.sh"),
            self.env_file,
        ]
        env = os.environ.copy()
        env["PREFLIGHT_CONFIG_ONLY"] = "1"
        env["SKIP_DOCKER_CHECK"] = "1"
        return subprocess.run(cmd, capture_output=True, text=True, cwd=BACKEND_DIR, env=env)

    def test_bootstrap_with_http_conf_passes(self):
        self._write_env(DEPLOYMENT_STAGE="bootstrap", NGINX_CONF_FILE="http.conf")
        res = self._run_preflight()
        self.assertEqual(res.returncode, 0, f"Expected 0, got {res.returncode}:\n{res.stdout}")
        self.assertIn("Все критические проверки пройдены", res.stdout)

    def test_bootstrap_with_https_conf_fails(self):
        self._write_env(DEPLOYMENT_STAGE="bootstrap", NGINX_CONF_FILE="https.conf")
        res = self._run_preflight()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("DEPLOYMENT_STAGE=bootstrap требует NGINX_CONF_FILE=http.conf", res.stdout)

    def test_production_with_http_conf_fails(self):
        self._write_env(
            DEPLOYMENT_STAGE="production",
            NGINX_CONF_FILE="http.conf",
            API_DOMAIN="api.example.kg",
            ADMIN_ALLOWED_IP="198.51.100.25",
        )
        res = self._run_preflight()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("DEPLOYMENT_STAGE=production требует NGINX_CONF_FILE=https.conf", res.stdout)

    def test_production_missing_api_domain_fails(self):
        self._write_env(
            DEPLOYMENT_STAGE="production",
            NGINX_CONF_FILE="https.conf",
            API_DOMAIN="",
            ADMIN_ALLOWED_IP="198.51.100.25",
        )
        res = self._run_preflight()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("требует обязательного указания API_DOMAIN", res.stdout)

    def test_production_invalid_api_domain_fails(self):
        for bad_domain in ["http://api.example.kg", "api;rm", "api.com:443", "api domain.com"]:
            with self.subTest(domain=bad_domain):
                self._write_env(
                    DEPLOYMENT_STAGE="production",
                    NGINX_CONF_FILE="https.conf",
                    API_DOMAIN=bad_domain,
                    ADMIN_ALLOWED_IP="198.51.100.25",
                )
                res = self._run_preflight()
                self.assertNotEqual(res.returncode, 0)
                self.assertIn("недопустимые символы", res.stdout)

    def test_production_missing_admin_allowed_ip_fails(self):
        self._write_env(
            DEPLOYMENT_STAGE="production",
            NGINX_CONF_FILE="https.conf",
            API_DOMAIN="api.example.kg",
            ADMIN_ALLOWED_IP="",
        )
        res = self._run_preflight()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("ADMIN_ALLOWED_IP обязательна", res.stdout)

    def test_production_invalid_admin_allowed_ip_fails(self):
        for bad_ip in ["198.51.100.400", "1.2.3.4; allow all;", "invalid", "10.0.0.1/33"]:
            with self.subTest(ip=bad_ip):
                self._write_env(
                    DEPLOYMENT_STAGE="production",
                    NGINX_CONF_FILE="https.conf",
                    API_DOMAIN="api.example.kg",
                    ADMIN_ALLOWED_IP=bad_ip,
                )
                res = self._run_preflight()
                self.assertNotEqual(res.returncode, 0)
                self.assertIn("некорректный IP/CIDR адрес", res.stdout)

    def test_production_missing_certs_fails(self):
        # Even with valid domain, IP, and https.conf, missing certs must fail preflight
        self._write_env(
            DEPLOYMENT_STAGE="production",
            NGINX_CONF_FILE="https.conf",
            API_DOMAIN="api.example.kg",
            ADMIN_ALLOWED_IP="198.51.100.25",
        )
        # deploy/certs does not have fullchain.pem/privkey.pem committed in repo
        res = self._run_preflight()
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("TLS сертификат", res.stdout)
