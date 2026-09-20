"""Личность студента для аутентификации (ТЗ п.18).

ПОЧЕМУ НЕ КЭШИРУЕТСЯ САМА МОДЕЛЬ
--------------------------------
Django-модель тянет за собой связанный University, весит в разы больше
нужного и перестаёт десериализоваться при любом изменении схемы — то есть
после каждого деплоя с миграцией кэш массово протухал бы молча.

Здесь кэшируется плоский словарь из шести полей. Он переживает миграции,
занимает сотни байт и не содержит ни телефона, ни email, ни фото, ни пароля —
в аутентификации они не нужны, а утечка PII из кэша никому не нужна.
"""
from dataclasses import dataclass

CACHE_FORMAT_VERSION = 1


@dataclass(frozen=True)
class StudentPrincipal:
    id: str
    student_code: str
    university_id: str
    full_name: str
    is_active: bool
    auth_version: int

    @classmethod
    def from_model(cls, student) -> "StudentPrincipal":
        return cls(
            id=str(student.id),
            student_code=student.student_id,
            university_id=str(student.university_id),
            full_name=student.full_name,
            is_active=student.is_active,
            auth_version=student.auth_version,
        )

    def to_cache(self) -> dict:
        return {
            "v": CACHE_FORMAT_VERSION,
            "id": self.id,
            "code": self.student_code,
            "uni": self.university_id,
            "name": self.full_name,
            "active": self.is_active,
            "av": self.auth_version,
        }

    @classmethod
    def from_cache(cls, payload):
        """Возвращает None для чужого или устаревшего формата.

        Тихо принять запись другой версии значило бы работать с неверными
        полями; безопаснее сходить в базу.
        """
        if not isinstance(payload, dict) or payload.get("v") != CACHE_FORMAT_VERSION:
            return None
        try:
            return cls(
                id=payload["id"],
                student_code=payload["code"],
                university_id=payload["uni"],
                full_name=payload["name"],
                is_active=payload["active"],
                auth_version=payload["av"],
            )
        except KeyError:
            return None
