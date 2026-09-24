"""PostgreSQL advisory transaction locks для синхронизации голосования.

ЗАЧЕМ ЭТО СУЩЕСТВУЕТ
--------------------
Раньше каждый голос брал `SELECT ... FOR UPDATE` на строке Election. Это делало
строку выборов единственной точкой сериализации: 10 000 параллельных голосов
выстраивались в очередь за одной row lock (ТЗ п.7).

Здесь используется другая пара блокировок по тому же ключу — идентификатору выборов:

  * голоса берут SHARED  -> держатся одновременно, друг друга не ждут;
  * смена состояния (start/finish/cancel/delete) берёт EXCLUSIVE ->
    ждёт завершения уже начатых голосов и не пускает новые в критическую секцию.

Так `finish` получает честный барьер (ТЗ п.8), а голоса остаются параллельными.

ПОЧЕМУ ИМЕННО ADVISORY, А НЕ ROW LOCK
-------------------------------------
Advisory-лок не привязан к строке, поэтому чтение Election не обязано быть
блокирующим. Лок транзакционный (`_xact_`): освобождается на COMMIT или ROLLBACK
автоматически, забыть его отпустить невозможно.

ЧЕГО ЗДЕСЬ БЫТЬ НЕ ДОЛЖНО
-------------------------
Никаких Python-локов между процессами и никаких Redis-локов вместо этих:
источник истины о принятом голосе — PostgreSQL, и только он (ТЗ п.8).
"""
import hashlib
import logging
import uuid as uuid_module
from typing import Union

from django.db import connection, transaction

logger = logging.getLogger(__name__)

# Идентификатор выборов приходит и как UUID (из модели), и как строка
# (из тела запроса, из кэша). Ключ лока обязан быть одинаковым в обоих
# случаях — иначе два воркера взяли бы разные локи и барьер завершения
# выборов перестал бы работать. Нормализация — в advisory_lock_key.
LockValue = Union[uuid_module.UUID, str]

_SIGNED_BIGINT_OFFSET = 2 ** 63


def supports_advisory_locks() -> bool:
    """Advisory-локи есть только в PostgreSQL."""
    return connection.vendor == "postgresql"


def advisory_lock_key(namespace: str, value: LockValue) -> int:
    """Стабильный знаковый int64 из пространства имён и значения.

    Встроенный hash() не подходит: он рандомизирован между процессами
    (PYTHONHASHSEED), поэтому два воркера получили бы разные ключи для одних
    и тех же выборов и не блокировали бы друг друга — то есть лок молча
    перестал бы работать. blake2b стабилен всегда.
    """
    # Нормализация обязательна: election_id приходит и строкой (из сериализатора),
    # и объектом UUID (из модели). Если бы они давали разные ключи, голос и
    # finish брали бы РАЗНЫЕ локи, и барьер молча перестал бы работать.
    if isinstance(value, uuid_module.UUID):
        raw = value.bytes
    else:
        try:
            raw = uuid_module.UUID(str(value)).bytes
        except (ValueError, AttributeError, TypeError):
            raw = str(value).encode("utf-8")

    digest = hashlib.blake2b(namespace.encode("utf-8") + b":" + raw, digest_size=8).digest()
    unsigned = int.from_bytes(digest, "big", signed=False)
    return unsigned - _SIGNED_BIGINT_OFFSET


def _require_transaction(what: str) -> None:
    """Вне транзакции pg_advisory_xact_lock освобождается немедленно.

    Молчаливый no-op здесь опаснее исключения: код выглядел бы защищённым,
    не будучи защищённым.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError(
            f"{what} должен вызываться внутри transaction.atomic(): "
            "advisory transaction lock вне транзакции освобождается немедленно "
            "и никакой защиты не даёт."
        )


def _acquire(sql: str, key: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql, [key])


def election_vote_lock(election_id: LockValue) -> None:
    """SHARED-лок выборов: берётся каждой транзакцией голосования.

    Несколько голосов одних выборов держат его одновременно — это и есть
    отказ от глобальной сериализации. Блокирует только exclusive-держателя,
    то есть операцию смены состояния выборов.
    """
    _require_transaction("election_vote_lock")
    if not supports_advisory_locks():
        logger.debug("advisory locks недоступны на %s — election_vote_lock пропущен", connection.vendor)
        return
    _acquire("SELECT pg_advisory_xact_lock_shared(%s)", advisory_lock_key("election", election_id))


def election_state_lock(election_id: LockValue) -> None:
    """EXCLUSIVE-лок выборов: берётся start/finish/cancel/delete.

    Ждёт, пока завершатся уже начатые голоса, и не пускает новые в критическую
    секцию, пока статус меняется. После COMMIT ожидающие голосования прочитают
    уже новый статус и будут отклонены (ТЗ п.8).
    """
    _require_transaction("election_state_lock")
    if not supports_advisory_locks():
        logger.debug("advisory locks недоступны на %s — election_state_lock пропущен", connection.vendor)
        return
    _acquire("SELECT pg_advisory_xact_lock(%s)", advisory_lock_key("election", election_id))
