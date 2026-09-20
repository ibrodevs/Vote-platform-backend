# Этап 7 — Production runtime и деплой: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development
> или superpowers:executing-plans.

**Goal:** Сделать так, чтобы небезопасная production-конфигурация не могла
запуститься молча, а приложение работало под нормальным application server
за реверс-прокси, с реальным Celery-воркером и вынесенной статикой.

**Architecture:** Настройки разделяются на базовые и production, но остаются
одним модулем с явными ветками — дробление на пакет `settings/` при текущем
размере файла добавило бы навигации больше, чем ясности. Ключевое:
`production_check` и валидация на старте превращают «мы забыли выставить
переменную» из инцидента в отказ запуска.

**Spec:** roadmap, этап 7; ТЗ п.13, 31, 32, 33, 37, 38, 39, 40, 41, 42, 43,
44, 45, 57, 59, 60, 95, 101, 102, 103. Дефекты D-06 (обработчик 500), D-10.

---

## Global Constraints

1. **Живой деплой не ломать.** Поведение без `DJANGO_ENV=production` остаётся
   прежним. Все строгие проверки включаются только явным режимом.
2. **Fail fast, а не fail silent (ТЗ п.102).** Небезопасная конфигурация
   обязана валить старт, а не работать «как-нибудь».
3. **Никаких секретов в Git (ТЗ п.33).** Текущий `SECRET_KEY` закоммичен —
   считается скомпрометированным.
4. **Голосование важнее админки (ТЗ п.42).** Тяжёлые административные
   операции не должны конкурировать с приёмом голосов.
5. **348 тестов остаются зелёными.**

---

## Порядок (каждый пункт — отдельный коммит)

### 1. Валидация конфигурации и `production_check` (п.32, 33, 102, 103; D-10)
- `apps/core/system_checks.py`: проверки Django system check framework.
- `production_check` — management-команда, пригодная для CI и для pre-deploy.
- Проверки: `DEBUG=False`, `SECRET_KEY` задан и не дефолтный и **не короче
  32 байт** (D-10: PyJWT предупреждает про HMAC SHA256), движок PostgreSQL,
  `ALLOWED_HOSTS` без `*`, CORS без `ALLOW_ALL`, `CELERY_TASK_ALWAYS_EAGER=False`,
  demo-OTP выключен, `X_FRAME_OPTIONS != ALLOWALL`, миграции применены.

### 2. Production-настройки (п.32, 33, 60, 95, 101)
- `ALLOWED_HOSTS`, CORS, CSRF из окружения; в production никаких `*`.
- Security-заголовки: HSTS, `SECURE_SSL_REDIRECT`, secure cookies,
  `X_FRAME_OPTIONS=DENY`, `SECURE_REFERRER_POLICY`, `X-Content-Type-Options`.
- Доверенные прокси: `X-Forwarded-For` нельзя принимать от кого угодно (п.60).
- Полный `.env.example` с группами и комментариями (п.101).

### 3. D-06: обработчик 500 (п.65)
- Наружу — generic-сообщение и `request_id`, подробности в лог.
- `request_id` генерируется middleware и возвращается заголовком.

### 4. Gunicorn (п.37, 38, 44, 45)
- `gunicorn.conf.py`, все параметры из окружения.
- Graceful shutdown, `max_requests` с jitter, таймауты.
- Выбор WSGI, а не ASGI — с обоснованием, что решение проверяется бенчмарком.

### 5. Статика и медиа мимо Django (п.31)
- Абстракция хранилища: локально — файловая система, в production — S3/CDN
  через `django-storages`, если задан бакет.
- URL в ответах не меняются (ограничение из `docs/FRONTEND_USAGE.md`).

### 6. Celery: очереди и импорт (п.40, 41, 42)
- Очереди `default / imports / notifications / maintenance`.
- Импорт студентов: файл не гоняется через брокер целиком, batch-вставка,
  метрики.
- Экспорт Excel изолируется от воркеров голосования.

### 7. Health-чеки (п.43)
- `/health/live` — процесс жив, без запросов в БД.
- `/health/ready` — PostgreSQL доступен, конфигурация валидна,
  состояние Redis известно. Redis недоступен ≠ not ready.

### 8. Dockerfile, compose и Nginx (п.13, 57, 59)
- Production Dockerfile: multi-stage, non-root, gunicorn, SIGTERM.
- `docker-compose.prod.yml` с PgBouncer.
- `deploy/nginx.conf`: keep-alive, таймауты, лимиты, real IP,
  без логирования `Authorization` и тела `POST /vote`.

### 9. Документация (п.100)
- `docs/DEPLOY_PRODUCTION.md`.

---

## Definition of Done

- [ ] `production_check` падает на каждой небезопасной настройке.
- [ ] Старт в production невозможен с `DEBUG=True`, коротким или дефолтным
      секретом, SQLite, wildcard-хостами, открытым CORS, demo-OTP.
- [ ] 500 не отдаёт内部 детали; в ответе есть `request_id`.
- [ ] Gunicorn настраивается окружением, без хардкода под одну машину.
- [ ] Статика и медиа не проходят через Django в production; URL те же.
- [ ] Celery работает воркером с разделёнными очередями.
- [ ] `/health/live` и `/health/ready` ведут себя по-разному и осмысленно.
- [ ] Dockerfile production без `runserver`, non-root.
- [ ] Есть пример Nginx и `docs/DEPLOY_PRODUCTION.md`.
- [ ] Поведение по умолчанию не изменилось; 348 тестов зелёные.
