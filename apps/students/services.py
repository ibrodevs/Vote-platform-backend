import re
import random
import logging
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from .models import StudentAuthSession

logger = logging.getLogger(__name__)

def clean_phone_number(phone: str) -> str:
    """Normalize phone number: digits only, ensuring country code."""
    digits = re.sub(r'\D', '', str(phone or ''))
    if digits.startswith('996') and len(digits) == 12:
        return f"+{digits}"
    if digits.startswith('0') and len(digits) == 10:
        return f"+996{digits[1:]}"
    if len(digits) == 9:
        return f"+996{digits}"
    if digits:
        return f"+{digits}"
    return ""

def generate_otp_code() -> str:
    """Generates a 6-digit OTP code."""
    if getattr(settings, 'MOCK_SMS', True):
        # In mock / demo mode, return default or random
        return getattr(settings, 'DEMO_OTP_CODE', '123456')
    return f"{random.randint(100000, 999999)}"

def send_student_otp(student, phone_number: str):
    """Создаёт сессию подтверждения и отправляет код.

    Возвращает кортеж (session, raw_code). Открытый код нужен вызывающему
    только для demo-режима; в базе он не хранится и в логи не попадает.
    """
    code = generate_otp_code()
    expires_at = timezone.now() + timedelta(minutes=getattr(settings, 'SMS_OTP_EXPIRY_MINUTES', 10))

    session = StudentAuthSession(
        student=student,
        phone_number=phone_number,
        expires_at=expires_at,
    )
    # Код хэшируется сразу: в базу он в открытом виде не попадает (ТЗ п.34)
    session.set_code(code)
    session.save()

    # В production здесь вызов SMS-шлюза.
    #
    # КОД НЕ ЛОГИРУЕТСЯ И НЕ ПЕЧАТАЕТСЯ. Раньше он уходил и в logger.info,
    # и в print вместе с телефоном и student_id: любой, у кого есть доступ
    # к логам, мог войти под этим студентом. В dev-режиме код возвращается
    # в HTTP-ответе — этого достаточно для разработки и не оставляет следов.
    logger.info(
        "otp_dispatched session_id=%s phone_suffix=%s",
        session.id, phone_number[-2:] if phone_number else '',
    )

    return session, code
