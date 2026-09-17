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
    """
    Creates an authentication session and sends OTP via SMS.
    Returns the created StudentAuthSession instance.
    """
    code = generate_otp_code()
    expires_at = timezone.now() + timedelta(minutes=getattr(settings, 'SMS_OTP_EXPIRY_MINUTES', 10))

    session = StudentAuthSession.objects.create(
        student=student,
        phone_number=phone_number,
        code=code,
        expires_at=expires_at
    )

    # In production, call SMS gateway (e.g. Twilio, SMS.kg, etc.)
    # In development/mock mode, log to console
    logger.info(f"===> [SMS DISPATCH] Sent OTP code {code} to {phone_number} for student {student.student_id} (Session: {session.id})")
    print(f"\n[DEMO SMS CODE] Code for {student.full_name} ({phone_number}): {code}\n")

    return session
