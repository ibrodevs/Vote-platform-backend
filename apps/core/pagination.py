"""Пагинация с ограничением сверху (ТЗ п.93).

Без `page_size_query_param` клиент не мог влиять на размер страницы вовсе.
С ним, но без `max_page_size`, любой запрос `?page_size=1000000` выгрузил бы
всю таблицу студентов одним ответом — это и отказ в обслуживании, и выгрузка
персональных данных пачкой.

`max_page_size` ограничивает сверху: значения больше него молча приводятся
к максимуму, а не вызывают ошибку — так клиент, попросивший слишком много,
получает корректный ответ, а не 400.
"""
from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 200
