"""
WSGI configuration for PythonAnywhere.

ИНСТРУКЦИЯ:
Скопируйте содержимое этого файла в файл WSGI конфигурации на PythonAnywhere:
/var/www/<ваш_username>_pythonanywhere_com_wsgi.py
(ссылка находится во вкладке "Web" -> "WSGI configuration file").

Замените 'YOUR_USERNAME' на ваш реальный логин на PythonAnywhere!
"""

import os
import sys

# 1. Ваш логин на PythonAnywhere (замените на ваш username!)
PA_USERNAME = 'YOUR_USERNAME'

# 2. Путь к директории backend на PythonAnywhere
# Если вы склонировали проект в корень: /home/USERNAME/Vote_project/backend
project_home = f'/home/{PA_USERNAME}/Vote_project/backend'

# Если проект загружен в другую папку или путь определен автоматически:
current_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(current_dir, 'manage.py')):
    project_home = current_dir

if project_home not in sys.path:
    sys.path.insert(0, project_home)

# 3. Установка переменной настроек Django
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

# 4. Загрузка .env файла (если он создан в папке backend)
try:
    from dotenv import load_dotenv
    env_file = os.path.join(project_home, '.env')
    if os.path.exists(env_file):
        load_dotenv(env_file)
except ImportError:
    pass

# 5. Запуск Django WSGI
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
