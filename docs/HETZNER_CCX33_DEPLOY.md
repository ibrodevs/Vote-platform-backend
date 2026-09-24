# Руководство по развёртыванию Vote Platform Backend на Hetzner Cloud CCX33

Документ содержит пошаговую инструкцию по первоначальному развёртыванию, настройке операционной системы, проверке и последующей эксплуатации backend-платформы голосования на выделенном облачном сервере Hetzner.

---

## 1. Спецификация целевого сервера

```text
Провайдер:      Hetzner Cloud
Локация:        Helsinki, Finland (HEL1)
План / Тип:     CCX33 (Dedicated vCPU)
Процессор:      8 dedicated AMD EPYC™ vCPU
Память:         32 GB RAM
Диск:           240 GB NVMe SSD
ОС:             Ubuntu 24.04 LTS (Noble Numbat)
```

Архитектура первой ноды объединяет следующие компоненты в едином Docker Compose контуре:
* **Nginx 1.27** (Edge reverse-proxy, TLS termination, rate limiting, static/media serving);
* **Django 5.2 / Gunicorn** (WSGI web-сервер с пулом потоков `gthread`);
* **PgBouncer 1.24** (Connection pooler в режиме `transaction pooling`);
* **PostgreSQL 16** (Primary ACID реляционная база данных, единственный source of truth);
* **Redis 7.4** (Кэш сессий и брокер очередей Celery, `allkeys-lru`, volatile);
* **Celery 5.6** (Раздельные воркеры `celery-default` и `celery-heavy`).

---

## 2. Первоначальный вход по SSH и безопасность

### 2.1. Вход под root
При создании сервера в консоли Hetzner Cloud выберите авторизацию по SSH-ключу:

```bash
ssh root@<SERVER_IP>
```

### 2.2. Создание системного пользователя с правами sudo
Не работайте в повседневном режиме напрямую под `root`:

```bash
adduser deployer
usermod -aG sudo deployer

# Копирование SSH-ключа новому пользователю
mkdir -p /home/deployer/.ssh
cp ~/.ssh/authorized_keys /home/deployer/.ssh/
chown -R deployer:deployer /home/deployer/.ssh
chmod 700 /home/deployer/.ssh
chmod 600 /home/deployer/.ssh/authorized_keys
```

### 2.3. Установка часового пояса
Для проекта голосования критична синхронизация времени (дедлайны выборов, таймстампы голосов):

```bash
timedatectl set-timezone Asia/Bishkek
timedatectl set-ntp on
timedatectl status
```

### 2.4. Настройка автоматических обновлений безопасности
```bash
apt update && apt install -y unattended-upgrades
dpkg-reconfigure --priority=low unattended-upgrades
```

### 2.5. Усиление конфигурации SSH (`/etc/ssh/sshd_config.d/99-hardened.conf`)
Создайте файл конфигурации SSH:

```bash
cat << 'EOF' > /etc/ssh/sshd_config.d/99-hardened.conf
# Отключение парольной аутентификации после проверки SSH-ключа
PasswordAuthentication no
ChallengeResponseAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
X11Forwarding no
MaxAuthTries 4
ClientAliveInterval 300
ClientAliveCountMax 2
EOF

systemctl reload ssh
```

> [!WARNING]
> Перед закрытием текущей root-сессии обязательно проверьте вход в новом терминале: `ssh deployer@<SERVER_IP>`.

---

## 3. Обновление ОС и настройка ядра (Swap & Sysctl)

### 3.1. Обновление пакетов
```bash
apt update && apt upgrade -y
apt install -y curl wget git ufw htop iotop net-tools ca-certificates gnupg lsb-release
```

### 3.2. Настройка Swap (4 GB)
Для высокопроизводительного сервера с PostgreSQL swap не должен использоваться как расширение оперативной памяти. Он необходим исключительно как амортизатор против мгновенного Linux OOM Killer:

```bash
# Выделение файла swap на NVMe
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile

# Добавление в fstab для монтирования при загрузке
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

### 3.3. Тюнинг ядра Linux (`/etc/sysctl.d/99-vote-tuning.conf`)
Параметры подобраны под 8 CPU, 32 GB RAM и высокую параллельную нагрузку (backlog, сокеты, файловые дескрипторы):

```bash
cat << 'EOF' > /etc/sysctl.d/99-vote-tuning.conf
# Swap: минимальное использование swap, сохранение RAM для дискового кэша
vm.swappiness = 10
vm.vfs_cache_pressure = 50

# Сетевой стек: размер очереди соединений (backlog) для Nginx и Gunicorn
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096

# Расширение диапазона эфемерных портов для исходящих прокси-соединений
net.ipv4.ip_local_port_range = 1024 65535

# Быстрое переиспользование сокетов в состоянии TIME_WAIT
net.ipv4.tcp_tw_reuse = 1

# Файловые дескрипторы: поддержка десятков тысяч одновременных сокетов
fs.file-max = 2097152

# Защита от переполнения ARP-кэша
net.ipv4.neigh.default.gc_thresh1 = 1024
net.ipv4.neigh.default.gc_thresh2 = 2048
net.ipv4.neigh.default.gc_thresh3 = 4096
EOF

sysctl --system
```

### 3.4. Лимиты файловых дескрипторов (`/etc/security/limits.d/99-vote.conf`)
```bash
cat << 'EOF' > /etc/security/limits.d/99-vote.conf
* soft nofile 65535
* hard nofile 65535
* soft nproc  32768
* hard nproc  32768
EOF
```

---

## 4. Установка Docker и Docker Compose

Установка официального Docker Engine из репозитория Docker:

```bash
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Добавление пользователя в группу docker
usermod -aG docker deployer

# Настройка ограничения размера логов Docker по умолчанию
cat << 'EOF' > /etc/docker/daemon.json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "5"
  }
}
EOF

systemctl restart docker
```

---

## 5. Настройка сетевого экрана (UFW Firewall)

В соответствии с требованиями безопасности наружу разрешены только порты 22, 80 и 443. Порты БД (5432), Redis (6379), PgBouncer (5432/6432) и Gunicorn (8000) закрыты наглухо и доступны исключительно внутри Docker-сети:

```bash
ufw default deny incoming
ufw default allow outgoing

# Разрешить SSH (при статическом IP администратора лучше указать `from <ADMIN_IP>`)
ufw allow 22/tcp

# Разрешить веб-трафик HTTP и HTTPS
ufw allow 80/tcp
ufw allow 443/tcp

# Включение фаервола
ufw enable
ufw status verbose
```

---

## 6. Клонирование репозитория и ветка деплоя

Перейдите под пользователя `deployer`:

```bash
su - deployer

mkdir -p ~/projects
cd ~/projects

git clone https://github.com/ibrodevs/Vote-platform-backend.git
cd Vote-platform-backend

# Переключение на ветку деплоя для Hetzner CCX33
git checkout deploy/hetzner-ccx33
```

---

## 7. Конфигурация `.env` и генерация секретов

### 7.1. Генерация секретных ключей
Сгенерируйте уникальные криптостойкие секреты для каждого компонента:

```bash
python3 -c "import secrets; print('DJANGO_SECRET_KEY=' + secrets.token_urlsafe(64))"
python3 -c "import secrets; print('DB_PASSWORD=' + secrets.token_urlsafe(32))"
python3 -c "import secrets; print('REDIS_PASSWORD=' + secrets.token_urlsafe(32))"
python3 -c "import secrets; print('METRICS_TOKEN=' + secrets.token_urlsafe(32))"
```

### 7.2. Создание файла `.env`
Скопируйте шаблон:

```bash
cp .env.example .env
nano .env
```

Заполните ключевые переменные для первого запуска (Mode A — без домена):

```env
# 1. Django core
DJANGO_ENV=production
DEPLOYMENT_STAGE=bootstrap
DJANGO_SECRET_KEY=<ВСТАВИТЬ_СГЕНЕРИРОВАННЫЙ_КЛЮЧ>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=<SERVER_IP>
DJANGO_CORS_ALLOWED_ORIGINS=http://<FRONTEND_IP_OR_HOST>
DJANGO_CSRF_TRUSTED_ORIGINS=http://<FRONTEND_IP_OR_HOST>

# 2. Database & PgBouncer
DB_ENGINE=postgresql
DB_NAME=vote_db
DB_USER=vote_user
DB_PASSWORD=<ВСТАВИТЬ_СГЕНЕРИРОВАННЫЙ_ПАРОЛЬ_БД>
DB_HOST=pgbouncer
DB_PORT=5432
DB_BEHIND_PGBOUNCER=True
DB_CONN_MAX_AGE=0
DB_CONNECT_TIMEOUT=10
PGBOUNCER_MAX_CLIENT_CONN=1000
PGBOUNCER_DEFAULT_POOL_SIZE=25

# 3. Redis
REDIS_PASSWORD=<ВСТАВИТЬ_СГЕНЕРИРОВАННЫЙ_ПАРОЛЬ_REDIS>
REDIS_URL=redis://:<ВСТАВИТЬ_ПАРОЛЬ_REDIS>@redis:6379/1
REDIS_MAXMEMORY=256mb

# 4. Celery
CELERY_BROKER_URL=redis://:<ВСТАВИТЬ_ПАРОЛЬ_REDIS>@redis:6379/0
CELERY_RESULT_BACKEND=redis://:<ВСТАВИТЬ_ПАРОЛЬ_REDIS>@redis:6379/0
CELERY_TASK_ALWAYS_EAGER=False
CELERY_DEFAULT_CONCURRENCY=4
CELERY_HEAVY_CONCURRENCY=2

# 5. Gunicorn WSGI
WEB_CONCURRENCY=4
GUNICORN_THREADS=4
GUNICORN_WORKER_CLASS=gthread

# 6. Nginx & SSL
NGINX_CONF_FILE=http.conf
DJANGO_SSL_REDIRECT=False
DJANGO_MEDIA_SHARED=True
METRICS_ENABLED=True
METRICS_TOKEN=<ВСТАВИТЬ_СГЕНЕРИРОВАННЫЙ_ТОКЕН_МЕТРИК>
```

---

## 8. Предполётная проверка (Preflight Check)

Перед запуском выполните скрипт валидации окружения:

```bash
./scripts/preflight.sh
```

Скрипт проверит:
* наличие и статус Docker и Docker Compose v2;
* корректность и заполненность всех секретов в `.env` (без вывода секретов в консоль);
* отсутствие утечки скомпрометированного ключа из репозитория;
* согласованность пары `DB_BEHIND_PGBOUNCER=True` и `DB_CONN_MAX_AGE=0`;
* доступность RAM (32 GB) и свободного места на NVMe (>20 GB);
* валидность синтаксиса `docker-compose.prod.yml`.

---

## 9. Пошаговый запуск (First Deployment Flow)

Деплой выполняется единой безопасной командой:

```bash
./scripts/deploy.sh
```

### Что делает `scripts/deploy.sh`:
1. **Сборка образов**: `docker compose -f docker-compose.prod.yml build`
2. **Запуск инфраструктуры**: `docker compose -f docker-compose.prod.yml up -d postgres redis pgbouncer`
3. **Ожидание healthcheck**: проверка готовности PostgreSQL, PgBouncer и Redis
4. **Миграции**: `docker compose -f docker-compose.prod.yml run --rm app python manage.py migrate --noinput`
5. **Статика**: `docker compose -f docker-compose.prod.yml run --rm app python manage.py collectstatic --noinput`
6. **Production Check**: `docker compose -f docker-compose.prod.yml run --rm app python manage.py production_check`
7. **Запуск сервисов**: `docker compose -f docker-compose.prod.yml up -d app celery-default celery-heavy nginx`
8. **Проверка жизнеспособности**: проверка `GET /health/live` и `GET /health/ready` через Nginx.

---

## 10. Проверка работоспособности

### 10.1. Статус контейнеров
```bash
docker compose -f docker-compose.prod.yml ps
```
Все контейнеры (`postgres`, `pgbouncer`, `redis`, `app`, `celery-default`, `celery-heavy`, `nginx`) должны находиться в состоянии `Up (healthy)`.

### 10.2. Проверка эндпоинтов здоровья
```bash
# Liveness (процесс жив)
curl -i http://<SERVER_IP>/health/live
# Ожидаемый ответ: 200 OK {"status": "alive"}

# Readiness (БД и кэш доступны, production проверки пройдены)
curl -i http://<SERVER_IP>/health/ready
# Ожидаемый ответ: 200 OK {"status": "ready", "checks": {"database": "ok", "cache": "ok", "config": "ok"}}
```

### 10.3. Просмотр логов
```bash
# Логи Nginx
docker compose -f docker-compose.prod.yml logs -f nginx

# Структурированные JSON-логи Django/Gunicorn
docker compose -f docker-compose.prod.yml logs -f app

# Логи очередей Celery
docker compose -f docker-compose.prod.yml logs -f celery-default celery-heavy

# Логи пулера и базы
docker compose -f docker-compose.prod.yml logs -f pgbouncer postgres
```

---

## 11. Нагрузочное тестирование (1k → 5k → 10k → 20k → 40k RPS)

> [!IMPORTANT]
> Нагрузочный генератор `k6` **НЕЛЬЗЯ** запускать на самом сервере CCX33. Генератор создаёт высокую нагрузку на собственный CPU и сетевой стек, искажая результаты тестирования приложения. Запускайте k6 с отдельной машины.

### 11.1. Добавление IP генератора нагрузки в allowlist Nginx
Чтобы Nginx rate limiter не блокировал генератор при эмуляции 1k–40k RPS с одного адреса, добавьте IP генератора в geo-блок файла `deploy/nginx/conf.d/http.conf`:

```nginx
geo $is_load_test_client {
    default 0;
    127.0.0.1 1;
    <LOAD_GENERATOR_IP> 1;  # IP вашего k6 сервера
}
```

Примените изменения:
```bash
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

### 11.2. Запуск ступенчатого теста с внешнего сервера
С машины генератора:
```bash
k6 run --env BASE_URL=http://<SERVER_IP> loadtests/k6/steps_to_40k.js
```

### 11.3. Мониторинг ресурсов на CCX33 во время теста
Откройте несколько терминалов на сервере:
1. `htop` — распределение загрузки по 8 vCPU;
2. `docker stats` — потребление памяти и CPU контейнерами `app`, `postgres`, `redis`, `pgbouncer`, `nginx`;
3. `iotop -o` — активность записи/чтения на NVMe SSD;
4. Логи медленных запросов PostgreSQL: `docker compose -f docker-compose.prod.yml logs -f postgres`.

### 11.4. Проверка целостности данных после тестов записи голосов
После прогона теста записи голосов (`profile_d_vote_write.js`) обязательно выполните аудит базы данных:

```bash
docker compose -f docker-compose.prod.yml run --rm app python manage.py audit_db_data
```

Команда проверяет:
* соответствие числа бюллетеней (`Ballot`) числу записей об участии (`VoteRecord`);
* отсутствие дубликатов голосов одного студента в рамках одних выборов;
* отсутствие голосов в выборах чужого университета;
* корректность подсчёта голосов.

---

## 12. Резервное копирование и восстановление

### 12.1. Ручное создание дампа
```bash
./scripts/backup.sh
```
Дамп в формате `pg_dump -Fc` сохраняется в `./backups/vote_db-YYYYMMDD-HHMMSS.dump`.

### 12.2. Верификация бэкапа (Restore Drill)
Проверка целостности снятого бэкапа без затрагивания рабочей базы:
```bash
./scripts/verify_backup.sh backups/vote_db-YYYYMMDD-HHMMSS.dump
```
Скрипт разворачивает дамп во временную базу, сверяет количество записей с рабочей базой и проверяет ссылочную целостность.

### 12.3. Настройка периодического бэкапа через Cron
Добавьте задачу в cron пользователя `deployer` (`crontab -e`):

```cron
# Ежедневный бэкап в 03:00 ночи с верификацией
0 3 * * * /home/deployer/projects/Vote-platform-backend/scripts/backup.sh >> /var/log/vote_backup.log 2>&1
```

### 12.4. Внешнее хранилище бэкапов
Хранение бэкапов на том же диске, где работает PostgreSQL, несёт критический риск потери данных при аварии сервера. Настройте Hetzner Storage Box или S3-совместимое хранилище:
```bash
# Экспорт переменной перед вызовом backup.sh
export S3_BACKUP_BUCKET=s3://my-hetzner-backup-bucket
./scripts/backup.sh
```

---

## 13. Процедура отката (Rollback Runbook)

Если после деплоя новой версии обнаружены ошибки:

1. **Откат кода на предыдущий тег/коммит**:
   ```bash
   git checkout <PREVIOUS_STABLE_COMMIT_OR_TAG>
   ```

2. **Пересборка и перезапуск контейнеров приложения**:
   ```bash
   docker compose -f docker-compose.prod.yml build app celery-default celery-heavy
   docker compose -f docker-compose.prod.yml up -d app celery-default celery-heavy nginx
   ```

3. **Если требуется откат базы данных**:
   Восстановите проверенный дамп, снятый перед деплоем:
   ```bash
   ./scripts/restore.sh backups/vote_db-PRE_DEPLOY.dump
   ```

---

## 14. Подключение домена и перевод в HTTPS (Mode B)

После регистрации домена и направления DNS A-записи на `<SERVER_IP>`:

### 14.1. Выпуск сертификата Let's Encrypt через Certbot
Сервер в Mode A (`http.conf`) уже настроен для обслуживания `/.well-known/acme-challenge/`:

```bash
# Установка certbot на хосте
sudo apt install -y certbot

# Получение сертификата через webroot
sudo certbot certonly --webroot \
  -w /var/lib/docker/volumes/vote-platform-backend_certbot_www/_data \
  -d api.yourdomain.kg \
  --email admin@yourdomain.kg --agree-tos --no-eff-email

# Копирование сертификатов в deploy/certs
cp /etc/letsencrypt/live/api.yourdomain.kg/fullchain.pem deploy/certs/
cp /etc/letsencrypt/live/api.yourdomain.kg/privkey.pem deploy/certs/
chmod 600 deploy/certs/privkey.pem
```

### 14.2. Переключение `.env` в Production Mode
Отредактируйте `.env`:
```env
DEPLOYMENT_STAGE=production
DJANGO_ALLOWED_HOSTS=api.yourdomain.kg,<SERVER_IP>
DJANGO_CORS_ALLOWED_ORIGINS=https://vote.yourdomain.kg
DJANGO_CSRF_TRUSTED_ORIGINS=https://vote.yourdomain.kg
DJANGO_SSL_REDIRECT=True
NGINX_CONF_FILE=https.conf
```

### 14.3. Применение конфигурации
```bash
docker compose -f docker-compose.prod.yml up -d app celery-default celery-heavy nginx
```

Проверьте доступность по HTTPS:
```bash
curl -i https://api.yourdomain.kg/health/ready
```
Backend переведён в полноценный боевой режим с TLS, HSTS и защищёнными cookie.
