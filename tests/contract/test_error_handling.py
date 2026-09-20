"""Обработка ошибок не раскрывает внутренности (ТЗ п.65, дефект D-06)."""
from unittest import mock

from django.test import override_settings

from apps.core.exceptions import GENERIC_SERVER_ERROR
from apps.core.middleware import REQUEST_ID_HEADER

from .base import ContractTestCase
from .factories import make_university


class RequestIdTest(ContractTestCase):
    def test_every_response_carries_request_id(self):
        res = self.client.get("/api/v1/universities/")
        self.assertTrue(res[REQUEST_ID_HEADER], "ответ без идентификатора запроса")

    def test_request_ids_differ_between_requests(self):
        a = self.client.get("/api/v1/universities/")[REQUEST_ID_HEADER]
        b = self.client.get("/api/v1/universities/")[REQUEST_ID_HEADER]
        self.assertNotEqual(a, b)

    def test_client_cannot_choose_request_id(self):
        """Подставленный клиентом id запутал бы разбор инцидента."""
        res = self.client.get(
            "/api/v1/universities/", HTTP_X_REQUEST_ID="подделка-клиента"
        )
        self.assertNotEqual(res[REQUEST_ID_HEADER], "подделка-клиента")


class UnhandledExceptionTest(ContractTestCase):
    """D-06: раньше 500 отдавал str(exc) — SQL, пути и значения переменных."""

    SECRET_FRAGMENT = "SELECT secret_column FROM internal_table /Users/deploy/app"

    def _trigger_500(self):
        with mock.patch(
            "apps.universities.views.UniversityPublicListView.get_queryset",
            side_effect=RuntimeError(self.SECRET_FRAGMENT),
        ):
            return self.client.get("/api/v1/universities/")

    @override_settings(DEBUG=False)
    def test_internal_details_do_not_leak(self):
        self.client.raise_request_exception = False
        res = self._trigger_500()
        self.assertEqual(res.status_code, 500)
        body = str(res.data)
        self.assertNotIn("SELECT secret_column", body)
        self.assertNotIn("/Users/deploy/app", body)
        self.assertNotIn("Traceback", body)

    @override_settings(DEBUG=False)
    def test_generic_message_is_returned(self):
        self.client.raise_request_exception = False
        res = self._trigger_500()
        self.assertEqual(res.data["error"]["code"], "internal_server_error")
        self.assertEqual(res.data["error"]["message"], GENERIC_SERVER_ERROR)

    @override_settings(DEBUG=False)
    def test_response_carries_request_id_for_support(self):
        """Без идентификатора сообщение об ошибке бесполезно обеим сторонам."""
        self.client.raise_request_exception = False
        res = self._trigger_500()
        self.assertIsNotNone(res.data["error"].get("request_id"))
        self.assertEqual(res.data["error"]["request_id"], res[REQUEST_ID_HEADER])

    @override_settings(DEBUG=False)
    def test_details_are_logged(self):
        """Подробности не исчезают — они уходят в лог."""
        self.client.raise_request_exception = False
        with self.assertLogs("apps.core.errors", level="ERROR") as captured:
            self._trigger_500()
        blob = "\n".join(captured.output)
        self.assertIn("SELECT secret_column", blob, "трейсбек должен попасть в лог")


class BusinessErrorsKeepTheirCodesTest(ContractTestCase):
    """Обычные ошибки не должны превратиться в generic-500."""

    def test_not_found_keeps_its_code(self):
        res = self.client.get("/api/v1/universities/nope/info/")
        self.assertEqual(res.status_code, 404)
        self.assertErrorEnvelope(res, "not_found")

    def test_validation_error_keeps_envelope(self):
        make_university(code="kstu")
        res = self.client.post(
            "/api/v1/auth/student/register/", {"email": "не-email"}, format="json"
        )
        self.assertEqual(res.status_code, 400)
        self.assertErrorEnvelope(res)

    def test_request_id_is_always_in_the_header(self):
        """Контракт: идентификатор есть в заголовке у ЛЮБОГО ответа.

        В теле он появляется только у ошибок, прошедших через обработчик
        исключений. Ответы, собранные во вьюхе вручную (их в проекте много),
        тела не меняют — поэтому опираться нужно на заголовок.
        """
        res = self.client.get("/api/v1/universities/nope/info/")
        self.assertEqual(res.status_code, 404)
        self.assertTrue(res[REQUEST_ID_HEADER])
