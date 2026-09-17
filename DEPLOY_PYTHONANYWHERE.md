# Пошаговая инструкция по деплою Backend на PythonAnywhere

Backend полностью подготовлен к работе на **PythonAnywhere**:
- **Открыт для всех запросов**: CORS разрешает любые домены (`*`), мобильные клиенты, фронтенд на Vercel, Netlify или локальный запуск.
- **CSRF & SSL Proxy**: Корректно настроены доверенные домены и заголовки `X-Forwarded-Proto` для работы по HTTPS.
- **Статические файлы и медиа**: Подключен WhiteNoise, настроена раздача медиа-файлов и фотографий кандидатов.
- **База данных**: Из коробки работает SQLite (не требует настройки), также поддерживается MySQL от PythonAnywhere.
- **Фоновые задачи**: Автоматически работают в режиме `EAGER` (не требуют отдельного Redis).

---

## Шаг 1. Регистрация и открытие консоли
1. Зарегистрируйтесь на сайте [PythonAnywhere](https://www.pythonanywhere.com/).
2. Перейдите во вкладку **Consoles** и откройте **Bash** консоль.

---

## Шаг 2. Загрузка проекта на сервер
В консоли Bash выполните клонирование вашего репозитория (или загрузите архив через вкладку **Files**):

```bash
git clone <URL_ВАШЕГО_РЕПОЗИТОРИЯ>
cd Vote_project/backend
```

*(Если проект находится в другой директории, убедитесь, что вы перешли в папку `backend`, где лежит `manage.py`)*.

---

## Шаг 3. Создание виртуального окружения и установка библиотек
В той же консоли Bash создайте виртуальное окружение с Python 3.11 или 3.12:

```bash
# Создание виртуального окружения
python3.11 -m venv ~/.virtualenvs/vote_env

# Активация окружения
source ~/.virtualenvs/vote_env/bin/activate

# Обновление pip и установка зависимостей
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Шаг 4. Применение миграций и сборка статики
Не выходя из активированного виртуального окружения, находясь в папке `backend`:

```bash
# Применение миграций базы данных
python manage.py migrate

# Создание учетной записи супер-администратора
python manage.py createsuperuser

# Сборка статических файлов
python manage.py collectstatic --noinput
```

*(Опционально)*: создайте файл конфигурации `.env`, скопировав пример:
```bash
cp .env.example .env
```

---

## Шаг 5. Настройка веб-приложения (Вкладка «Web»)
1. Откройте вкладку **Web** в панели управления PythonAnywhere.
2. Нажмите синюю кнопку **Add a new web app**.
3. Выберите опцию **Manual configuration** (ВНИМАНИЕ: не выбирайте "Django", выбирайте именно **Manual configuration**).
4. Выберите версию Python: **Python 3.11** (или 3.12, которую вы выбрали в Шаге 3).
5. После создания приложения настройте следующие секции:

### 1) Code (Пути к коду)
- **Source code:** `/home/<ВАШ_USERNAME>/Vote_project/backend`
- **Working directory:** `/home/<ВАШ_USERNAME>/Vote_project/backend`

### 2) Virtualenv (Виртуальное окружение)
- Нажмите на ссылку и укажите путь:
  `/home/<ВАШ_USERNAME>/.virtualenvs/vote_env`
  *(после ввода появится зеленая галочка)*

### 3) WSGI configuration file
- Нажмите на ссылку с путем вида `/var/www/<username>_pythonanywhere_com_wsgi.py`.
- Полностью удалите весь шаблонный текст в редакторе.
- Скопируйте и вставьте содержимое из файла `pythonanywhere_wsgi.py`:

```python
import os
import sys

# Замените YOUR_USERNAME на ваш логин на PythonAnywhere!
PA_USERNAME = 'YOUR_USERNAME'

project_home = f'/home/{PA_USERNAME}/Vote_project/backend'

if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

try:
    from dotenv import load_dotenv
    env_file = os.path.join(project_home, '.env')
    if os.path.exists(env_file):
        load_dotenv(env_file)
except ImportError:
    pass

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```
- Замените `'YOUR_USERNAME'` на ваш логин и нажмите кнопку **Save** вверху справа.

### 4) Static files (Раздача статики и медиа Nginx-сервером)
В секции **Static files** добавьте две записи:

| URL | Directory path |
|---|---|
| `/static/` | `/home/<ВАШ_USERNAME>/Vote_project/backend/staticfiles` |
| `/media/` | `/home/<ВАШ_USERNAME>/Vote_project/backend/media` |

---

## Шаг 6. Перезапуск и проверка
1. В самом верху страницы **Web** нажмите зеленую кнопку **Reload <ваш_username>.pythonanywhere.com**.
2. Откройте в браузере адрес вашего сайта:
   `https://<ваш_username>.pythonanywhere.com/`

Вы должны увидеть статус готовности API:
```json
{
  "status": "online",
  "message": "Voting Platform API is operational and accepting requests from all origins.",
  "version": "1.0.0",
  "endpoints": { ... }
}
```

Административная панель Django доступна по адресу:
`https://<ваш_username>.pythonanywhere.com/admin-django/`

---

## Шаг 7. Подключение фронтенда (Next.js) к вашему бэкенду
Для подключения фронтенда (на локальном компьютере, Vercel или любом хостинге):
1. В корне проекта фронтенда создайте или измените файл `.env.local`:
   ```env
   NEXT_PUBLIC_API_URL=https://<ваш_username>.pythonanywhere.com/api/v1
   ```
2. Теперь все запросы регистрации, авторизации, бюллетеня и админ-панели будут автоматически уходить на ваш бэкенд на PythonAnywhere!
