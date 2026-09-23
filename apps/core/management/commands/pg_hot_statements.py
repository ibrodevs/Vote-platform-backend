"""Топ SQL-запросов по реальному потраченному времени (ТЗ п.83, 84).

`explain_hot_queries` отвечает на вопрос «как база выполняет запрос, который
я считаю горячим». Эта команда отвечает на другой вопрос — «какие запросы
горячие на самом деле», и ответ берётся из статистики PostgreSQL, а не из
предположений разработчика. Этап 11 запрещает оптимизировать что-либо,
не показанное измерением.

Запросы в pg_stat_statements нормализованы: литералы заменены на $1, $2, …
Поэтому в выводе физически не может оказаться ни email, ни идентификатора
студента, ни кандидата — требование тайны голосования (ТЗ п.3, 4) выполняется
самим источником данных.

    python manage.py pg_hot_statements --reset      # перед прогоном нагрузки
    python manage.py pg_hot_statements --top 20     # после прогона
    python manage.py pg_hot_statements --format markdown > /tmp/hot.md
"""
from django.core.management.base import BaseCommand
from django.db import connection

# Служебные запросы самого измерения и psql-интроспекции: их присутствие
# в топе ничего не говорит о приложении и только вытесняет полезные строки.
NOISE_PREFIXES = (
    "SELECT pg_stat_statements",
    "select pg_stat_statements",
    "SELECT calls",
    "CREATE EXTENSION",
    "SET ",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
)


class Command(BaseCommand):
    help = "Показывает запросы, съевшие больше всего времени базы."

    def add_arguments(self, parser):
        parser.add_argument("--top", type=int, default=15, help="Сколько строк показать.")
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Обнулить статистику и выйти. Делается ПЕРЕД прогоном нагрузки.",
        )
        parser.add_argument("--format", choices=["text", "markdown"], default="text")
        parser.add_argument(
            "--include-noise",
            action="store_true",
            help="Не отфильтровывать BEGIN/COMMIT/SET и служебные запросы.",
        )

    def handle(self, *args, **opts):
        if connection.vendor != "postgresql":
            self.stderr.write("pg_stat_statements существует только в PostgreSQL")
            return

        if not self._extension_available():
            self.stderr.write(
                "Расширение pg_stat_statements не установлено.\n"
                "В docker-compose PostgreSQL должен стартовать с\n"
                "  -c shared_preload_libraries=pg_stat_statements\n"
                "после чего один раз выполнить:\n"
                "  CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"
            )
            return

        if opts["reset"]:
            with connection.cursor() as cur:
                cur.execute("SELECT pg_stat_statements_reset()")
            self.stdout.write(self.style.SUCCESS("Статистика обнулена."))
            return

        rows = self._collect(opts["top"], opts["include_noise"])
        if not rows:
            self.stdout.write("Статистика пуста — прогоните нагрузку после --reset.")
            return

        total_ms = self._total_time()
        if opts["format"] == "markdown":
            self._render_markdown(rows, total_ms)
        else:
            self._render_text(rows, total_ms)

    def _extension_available(self) -> bool:
        with connection.cursor() as cur:
            cur.execute("SELECT to_regclass('public.pg_stat_statements') IS NOT NULL")
            return bool(cur.fetchone()[0])

    def _total_time(self) -> float:
        with connection.cursor() as cur:
            cur.execute("SELECT COALESCE(sum(total_exec_time), 0) FROM pg_stat_statements")
            return float(cur.fetchone()[0])

    def _collect(self, top: int, include_noise: bool):
        # Выбирается с запасом: часть строк отсеется как служебная.
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT calls,
                       total_exec_time,
                       mean_exec_time,
                       rows,
                       shared_blks_hit,
                       shared_blks_read,
                       query
                FROM pg_stat_statements
                ORDER BY total_exec_time DESC
                LIMIT %s
                """,
                [top * 4],
            )
            raw = cur.fetchall()

        result = []
        for calls, total, mean, rows_out, hit, read, query in raw:
            flat = " ".join(str(query).split())
            if not include_noise and flat.startswith(NOISE_PREFIXES):
                continue
            result.append(
                {
                    "calls": calls,
                    "total_ms": float(total),
                    "mean_ms": float(mean),
                    "rows": rows_out,
                    "hit": hit,
                    "read": read,
                    "query": flat,
                }
            )
            if len(result) >= top:
                break
        return result

    def _render_text(self, rows, total_ms):
        self.stdout.write(f"Суммарное время всех запросов: {total_ms:.0f} мс\n")
        header = f"{'calls':>9}  {'total_ms':>10}  {'mean_ms':>8}  {'%время':>7}  query"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for r in rows:
            share = (r["total_ms"] / total_ms * 100) if total_ms else 0.0
            query = r["query"][:110]
            self.stdout.write(
                f"{r['calls']:>9}  {r['total_ms']:>10.1f}  {r['mean_ms']:>8.3f}  "
                f"{share:>6.1f}%  {query}"
            )

    def _render_markdown(self, rows, total_ms):
        self.stdout.write(f"Суммарное время всех запросов: **{total_ms:.0f} мс**\n")
        self.stdout.write("| calls | total_ms | mean_ms | % времени | rows | query |")
        self.stdout.write("|---:|---:|---:|---:|---:|---|")
        for r in rows:
            share = (r["total_ms"] / total_ms * 100) if total_ms else 0.0
            query = r["query"][:160].replace("|", "\\|")
            self.stdout.write(
                f"| {r['calls']} | {r['total_ms']:.1f} | {r['mean_ms']:.3f} | "
                f"{share:.1f}% | {r['rows']} | `{query}` |"
            )
