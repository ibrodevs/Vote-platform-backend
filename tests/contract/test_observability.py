"""Телеметрия не должна раскрывать тайну голосования (ТЗ п.4, 61, 62, 63)."""
import json
import logging

from django.test import override_settings
from prometheus_client import REGISTRY, generate_latest

from apps.core.logging import JSONFormatter, scrub_mapping, scrub_text
from apps.students.models import Student
from apps.students.services_auth import create_student_token

from .base import ContractTestCase
from .factories import make_candidate, make_election, make_university


class LogScrubbingTest(ContractTestCase):
    def test_bearer_token_is_removed(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature"
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", scrub_text(text))

    def test_bare_jwt_is_removed(self):
        text = "токен eyJhbGciOiJIUzI1NiJ9abcdefghijklmnopqrstuvwxyz получен"
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9abcdefghij", scrub_text(text))

    def test_forbidden_keys_are_redacted(self):
        cleaned = scrub_mapping({
            "authorization": "Bearer abc",
            "password": "секрет",
            "code": "123456",
            "candidate_id": "3f2a",
            "student_id": "7b1c",
            "election_id": "оставить",
        })
        for key in ("authorization", "password", "code", "candidate_id", "student_id"):
            self.assertEqual(cleaned[key], "[вырезано]", key)
        self.assertEqual(cleaned["election_id"], "оставить",
                         "election_id разрешён и вырезаться не должен")

    def test_nested_dicts_are_scrubbed(self):
        cleaned = scrub_mapping({"outer": {"password": "секрет"}})
        self.assertEqual(cleaned["outer"]["password"], "[вырезано]")


class JSONFormatterTest(ContractTestCase):
    def _format(self, **extra):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="сообщение", args=(), exc_info=None,
        )
        for key, value in extra.items():
            setattr(record, key, value)
        return json.loads(JSONFormatter().format(record))

    def test_output_is_valid_json(self):
        payload = self._format()
        self.assertEqual(payload["message"], "сообщение")
        self.assertEqual(payload["level"], "INFO")
        self.assertIn("instance", payload)

    def test_request_fields_are_included(self):
        payload = self._format(request_id="abc", method="POST",
                               route="/api/v1/voting/cast/", status=200,
                               duration_ms=12.5)
        self.assertEqual(payload["request_id"], "abc")
        self.assertEqual(payload["route"], "/api/v1/voting/cast/")
        self.assertEqual(payload["duration_ms"], 12.5)

    def test_context_is_scrubbed(self):
        payload = self._format(context={"password": "секрет", "ok": "значение"})
        self.assertEqual(payload["context"]["password"], "[вырезано]")
        self.assertEqual(payload["context"]["ok"], "значение")


class AccessLogPrivacyTest(ContractTestCase):
    """Лог доступа не должен содержать ни токена, ни выбора студента."""

    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест", course=1
        )
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)
        self.token = create_student_token(self.student)

    def test_vote_request_log_has_no_candidate_or_token(self):
        with self.assertLogs("apps.core.access", level="INFO") as captured:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(
                    "/api/v1/voting/cast/",
                    {"election_id": str(self.election.id),
                     "candidate_id": str(self.candidate.id)},
                    format="json",
                    HTTP_AUTHORIZATION=f"Bearer {self.token}",
                )
        blob = "\n".join(captured.output)
        self.assertNotIn(str(self.candidate.id), blob, "candidate_id в логе доступа")
        self.assertNotIn(str(self.student.id), blob, "student_id в логе доступа")
        self.assertNotIn(self.token, blob, "токен в логе доступа")

    def test_route_is_a_pattern_not_a_path(self):
        """Путь с подставленным id раздул бы кардинальность метрик."""
        with self.assertLogs("apps.core.access", level="INFO") as captured:
            self.client.get(f"/api/v1/elections/{self.election.id}/")
        blob = "\n".join(captured.output)
        self.assertNotIn(str(self.election.id), blob,
                         "в маршруте подставлен идентификатор вместо шаблона")


class MetricsPrivacyTest(ContractTestCase):
    """ТЗ п.63: метрики не должны раскрывать, кто за кого голосовал."""

    def setUp(self):
        super().setUp()
        self.uni = make_university()
        self.election = make_election(self.uni)
        self.candidate = make_candidate(self.election)
        self.student = Student.objects.create(
            university=self.uni, student_id="S-1", full_name="Тест", course=1
        )

    def test_no_metric_has_student_label(self):
        forbidden = {"student", "student_id", "user", "user_id", "voter"}
        for metric in REGISTRY.collect():
            if not metric.name.startswith("vote_"):
                continue
            for sample in metric.samples:
                offending = forbidden & set(sample.labels)
                with self.subTest(metric=metric.name):
                    self.assertEqual(offending, set(),
                                     f"{metric.name} содержит метку студента")

    def test_no_metric_has_candidate_label(self):
        """Счётчик по кандидату вместе с временем сузил бы круг до одного."""
        for metric in REGISTRY.collect():
            if not metric.name.startswith("vote_"):
                continue
            for sample in metric.samples:
                with self.subTest(metric=metric.name):
                    self.assertNotIn("candidate_id", sample.labels)
                    self.assertNotIn("candidate", sample.labels)

    def test_vote_metric_records_election_and_outcome_only(self):
        from apps.core.metrics import record_vote_attempt

        record_vote_attempt(self.election.id, "accepted")
        output = generate_latest().decode()
        self.assertIn("vote_attempts_total", output)
        self.assertIn(str(self.election.id), output, "election_id разрешён (ТЗ п.63)")
        self.assertNotIn(str(self.candidate.id), output)
        self.assertNotIn(str(self.student.id), output)

    def test_exported_metrics_contain_no_student_identifiers(self):
        token = create_student_token(self.student)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                "/api/v1/voting/cast/",
                {"election_id": str(self.election.id),
                 "candidate_id": str(self.candidate.id)},
                format="json", HTTP_AUTHORIZATION=f"Bearer {token}",
            )
        output = generate_latest().decode()
        self.assertNotIn(str(self.student.id), output)
        self.assertNotIn(str(self.candidate.id), output)
        self.assertNotIn(self.student.student_id, output)


class MetricsEndpointTest(ContractTestCase):
    def test_metrics_available_without_token_when_unset(self):
        res = self.client.get("/metrics")
        self.assertEqual(res.status_code, 200)
        self.assertIn("vote_http_requests_total", res.content.decode())

    @override_settings(METRICS_TOKEN="секретный-токен")
    def test_metrics_require_token_when_configured(self):
        """Публичный /metrics — это и разведка, и утечка предварительных итогов."""
        self.assertEqual(self.client.get("/metrics").status_code, 403)
        ok = self.client.get("/metrics", HTTP_AUTHORIZATION="Bearer секретный-токен")
        self.assertEqual(ok.status_code, 200)

    @override_settings(METRICS_ENABLED=False)
    def test_metrics_can_be_disabled(self):
        self.assertEqual(self.client.get("/metrics").status_code, 404)

    def test_http_metrics_are_recorded(self):
        self.client.get("/api/v1/universities/")
        output = generate_latest().decode()
        self.assertIn("vote_http_requests_total", output)
        self.assertIn("vote_http_request_duration_seconds", output)
