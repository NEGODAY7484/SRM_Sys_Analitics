"""Update chapters 2 and 3 in `docs/ВКР_Саша.docx` to match the current project.

This script is intentionally deterministic and limited in scope:
- It finds the *body* occurrences of "Глава 2" and "Глава 3" (the second occurrence, after the table of contents).
- It removes placeholder text for sections 2.* and 3.* and inserts detailed content aligned with the repo.

Run (PowerShell):
  python tools/update_vkr_sasha_chapters.py
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph

DOC_PATH = Path("docs") / "ВКР_Саша.docx"
OUT_PATH = Path("docs") / "ВКР_Саша_обновлено_главы_2_3.docx"


def _remove_paragraph(paragraph) -> None:
    """Remove a paragraph from a python-docx document."""

    p = paragraph._element  # noqa: SLF001 (python-docx internal API)
    p.getparent().remove(p)


def _insert_after(paragraph, text: str, *, style_name: str) -> object:
    """Insert a new paragraph after the given paragraph and return it."""

    new_p = OxmlElement("w:p")
    paragraph._element.addnext(new_p)  # noqa: SLF001 (python-docx internal API)
    new_par = Paragraph(new_p, paragraph._parent)  # noqa: SLF001
    new_par.add_run(text)
    new_par.style = style_name
    return new_par


def _clean_heading_paragraph(p) -> None:
    """Keep only the first line of a heading paragraph (removes old placeholder text)."""

    first_line = (p.text or "").splitlines()[0].strip()
    p.text = first_line


def main() -> None:
    if not DOC_PATH.exists():
        raise SystemExit(f"Не найден файл: {DOC_PATH}")

    doc = Document(str(DOC_PATH))
    ps = doc.paragraphs

    # We avoid hardcoding indices: find "Глава 2" and "Глава 3" occurrences and take the second one
    # (the first is usually inside the Contents).
    def find_all(term: str) -> list[int]:
        return [i for i, p in enumerate(ps) if term in (p.text or "")]

    ch2_idxs = find_all("Глава 2")
    ch3_idxs = find_all("Глава 3")
    lit_idxs = find_all("Список литературы")

    if len(ch2_idxs) < 2 or len(ch3_idxs) < 2 or len(lit_idxs) < 2:
        raise SystemExit(
            "Не удалось найти позиции глав (ожидались как минимум 2 вхождения: в содержании и в тексте)."
        )

    ch2 = ch2_idxs[-1]
    ch3 = ch3_idxs[-1]
    lit = lit_idxs[-1]

    # Subsections are expected to be close to the chapter headings
    # 2.1/2.2/2.3 inside [ch2, ch3), and 3.1/3.2/3.3 inside [ch3, lit)
    def find_in_range(prefix: str, start: int, end: int) -> int:
        for i in range(start, end):
            t = (ps[i].text or "").strip()
            if t.startswith(prefix):
                return i
        raise SystemExit(f"Не найден раздел {prefix} в диапазоне {start}..{end}")

    s21 = find_in_range("2.1.", ch2, ch3)
    s22 = find_in_range("2.2.", ch2, ch3)
    s23 = find_in_range("2.3.", ch2, ch3)
    s31 = find_in_range("3.1.", ch3, lit)
    s32 = find_in_range("3.2.", ch3, lit)
    s33 = find_in_range("3.3.", ch3, lit)

    # The document uses a custom mapping where most paragraphs are "Heading 1".
    # We keep this style for consistency.
    base_style = ps[ch2].style.name

    # 1) Clean heading paragraphs (remove old placeholder text after newlines)
    for idx in [s21, s22, s23, s31, s32, s33]:
        _clean_heading_paragraph(ps[idx])

    # 2) Remove all paragraphs between s23..ch3 and s33..lit that are placeholder-only
    # Current draft has placeholder content packed into these paragraphs; we remove everything between:
    # - after 2.3 heading and before chapter 3 heading
    # - after 3.3 heading and before literature
    # Additionally, we remove any extra "placeholder" paragraphs directly after headings if they exist.
    # We perform deletions from bottom to top to keep indices stable.
    to_delete: list[int] = []

    # After 2.3 heading up to chapter 3 heading (exclusive)
    for i in range(s23 + 1, ch3):
        if (ps[i].text or "").strip():
            to_delete.append(i)

    # After 3.3 heading up to literature (exclusive)
    for i in range(s33 + 1, lit):
        if (ps[i].text or "").strip():
            to_delete.append(i)

    for i in sorted(to_delete, reverse=True):
        _remove_paragraph(ps[i])

    # Refresh paragraph list references after deletions.
    # `doc.paragraphs` is computed from the current document XML; re-bind for stable indexing.
    ps = doc.paragraphs

    # Re-find anchors after deletion
    ch2 = find_all("Глава 2")[-1]
    ch3 = find_all("Глава 3")[-1]
    lit = find_all("Список литературы")[-1]
    s21 = find_in_range("2.1.", ch2, ch3)
    s22 = find_in_range("2.2.", ch2, ch3)
    s23 = find_in_range("2.3.", ch2, ch3)
    s31 = find_in_range("3.1.", ch3, lit)
    s32 = find_in_range("3.2.", ch3, lit)
    s33 = find_in_range("3.3.", ch3, lit)

    base_style = ps[ch2].style.name

    # -----------------------------
    # Insert new content (Ch.2)
    # -----------------------------
    p = ps[s21]
    p = _insert_after(
        p,
        (
            "Сервисный центр по ремонту техники представляет собой организацию, выполняющую приём устройств от клиентов, "
            "диагностику, согласование стоимости, ремонт, выдачу и последующее гарантийное обслуживание. "
            "Дополнительно сервисный центр ведёт склад запчастей и взаимодействует с поставщиками, формируя закупки "
            "комплектующих (дисплеи, аккумуляторы, шлейфы, платы и др.)."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "В проекте предметная область формализована через две группы процессов: "
            "CRM-процессы (клиенты и ремонтные заказы) и SRM-процессы (поставщики, закупки и контроль нарушений). "
            "CRM-часть обеспечивает операционную работу сервисного центра, а SRM-часть — аналитическую поддержку "
            "принятия решений по закупкам и рискам поставщиков."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "Основные участники процессов и их роли в системе:\n"
            "— администратор (admin): управление пользователями, настройками, правилами и доступом;\n"
            "— менеджер (manager): ведение заказов, закупок и запуск анализа;\n"
            "— мастер (master): исполнение заказов на ремонт, просмотр связанных данных;\n"
            "— аналитик (analyst): запуск анализа SRM, обработка нарушений и отчётов."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "Нормативные правила закупочной деятельности для сервисного центра включают ограничения по бюджету, "
            "контроль статусов и рейтингов поставщиков, сроков поставки и обязательности гарантийных условий. "
            "В рамках проекта данные правила представлены онтологическим слоем в формате JSON "
            "(см. файл `examples/repair_rules_ontology.json`), который интерпретируется системой во время выполнения."
        ),
        style_name=base_style,
    )

    p = ps[s22]
    p = _insert_after(
        p,
        (
            "Анализ существующих процессов (AS-IS) показывает, что основная часть контроля закупок часто выполняется вручную "
            "или в электронных таблицах, что приводит к типовым проблемам: несвоевременному выявлению просрочек поставки, "
            "перерасходу бюджета, закупкам у не одобренных поставщиков и отсутствию фиксируемых объяснений причин нарушений."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "Для рассматриваемой предметной области критичны следующие типы отклонений:\n"
            "— превышение планового бюджета закупки;\n"
            "— поставщик имеет статус blocked/risky либо не входит в список одобренных;\n"
            "— нарушение сроков поставки (план/факт);\n"
            "— закупка без гарантии либо гарантия ниже установленного минимума;\n"
            "— завышенная цена относительно средней по категории;\n"
            "— повторяющиеся нарушения у одного поставщика."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "В рамках дипломного проекта подчёркивается отличие от табличного подхода: система хранит историю запусков анализа, "
            "историю риска поставщиков, формирует единый реестр нарушений, а также выдаёт объяснения и рекомендации "
            "на основе онтологии правил. Данные функции трудно реализуются в Excel без значительных ручных процедур "
            "и без потери воспроизводимости результатов."
        ),
        style_name=base_style,
    )

    p = ps[s23]
    p = _insert_after(
        p,
        (
            "Функциональные требования к системе сформированы на основе сценариев работы сервисного центра и включают:\n"
            "1) ведение CRM-сущностей (клиенты, устройства, заказы на ремонт, склад запчастей, задачи);\n"
            "2) ведение SRM-сущностей (поставщики, категории, закупки, нарушения, запуски анализа, наборы правил);\n"
            "3) выполнение анализа закупок (CLI, API `/analyze`, запуск из веб-интерфейса) с формированием:\n"
            "   — отчёта в JSON;\n"
            "   — графиков (PNG);\n"
            "   — логов процесса анализа;\n"
            "   — записей о нарушениях в SQLite (таблица `violations`)."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "Нефункциональные требования включают: локальный офлайн-запуск, простота установки, воспроизводимость результатов, "
            "расширяемость онтологии правил и агентного слоя, а также пригодность к развёртыванию на сервере ВУЗа. "
            "Для выполнения требования офлайн-работы выбран стек: Python 3.10+, FastAPI, Jinja2, SQLite и локальная генерация графиков."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "Требования к демонстрационным данным. В проекте используются два набора данных:\n"
            "— базовый набор для быстрого старта, загружаемый из `examples/repair_demo_data.json` "
            "(5 поставщиков, 5 категорий, 5 закупок, 3 клиента, 3 устройства, 3 заказа, 3 позиции склада и 2 задачи);\n"
            "— расширенный набор для нагрузочного и функционального тестирования, формируемый командой "
            "`python -m srm.cli seed-large-demo` с параметрами объёма. По умолчанию создаются 100 клиентов, 150 устройств, "
            "300 заказов, 30 поставщиков, 12 категорий, 500 складских позиций, 1000 движений склада, 700 закупок, "
            "250 нарушений, 50 запусков анализа и история риска поставщиков (см. модуль `src/srm/web/seed_large.py`)."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "Ключевые численные параметры онтологии правил задаются в файле `examples/repair_rules_ontology.json` и используются "
            "в анализе без изменения кода. В текущей конфигурации установлены следующие значения:\n"
            "— допустимая задержка поставки: `delivery.allowed_delay_days = 2` дня;\n"
            "— минимальный рейтинг поставщика: `risk.min_supplier_rating = 3.0`;\n"
            "— минимальная гарантия на запчасть: `warranty.required_min_months = 3` месяца;\n"
            "— порог завышения цены относительно средней по категории: `price.max_over_avg_pct = 35%`;\n"
            "— порог повторяющихся нарушений: `recurrence.supplier_violations_threshold = 2`;\n"
            "— параметры предиктивной оценки (базовые вероятности): `predictions.base_delay_probability = 0.2`, "
            "`predictions.base_budget_probability = 0.15`."
        ),
        style_name=base_style,
    )

    # -----------------------------
    # Insert new content (Ch.3)
    # -----------------------------
    p = ps[s31]
    p = _insert_after(
        p,
        (
            "Разработанная система реализована как локальное веб-приложение на базе FastAPI с серверной генерацией HTML "
            "(Jinja2) и хранением данных в SQLite. Код разделён по слоям: загрузка данных (`srm.data`), "
            "онтология правил (`srm.ontology`), интеллектуальная логика анализа (`srm.agents`, `srm.logic`) и веб-слой (`srm.web`)."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "Модель данных отражена в SQLite-схеме (см. модуль `src/srm/web/db.py`) и включает ключевые сущности:\n"
            "— `clients`, `devices`, `repair_orders`, `order_history` (CRM);\n"
            "— `inventory_items`, `inventory_moves`, `order_parts`, `order_photos` (склад и использование запчастей);\n"
            "— `suppliers`, `supplier_categories`, `purchases` (SRM);\n"
            "— `violations`, `analysis_runs`, `rulesets`, `supplier_risk_history` (анализ, нарушения и риск-профиль)."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "Для обеспечения производительности при работе с увеличенным набором данных применяются индексы и пагинация. "
            "Пагинация реализована на страницах списков (клиенты, устройства, заказы, поставщики, закупки, нарушения, запуски анализа) "
            "с параметрами `page` и `page_size`. Индексы создаются в рамках инициализации БД (вызов `migrate_db()`), "
            "что позволяет ускорить фильтрацию по статусам и датам."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "Рис. 1 – Страница авторизации: ввод логина/пароля и выбор сценария входа.\n"
            "Рис. 2 – Главная панель (Dashboard): KPI, последние события и быстрые переходы.\n"
            "Рис. 3 – Список заказов: таблица заказов, фильтры по статусу и датам, быстрые действия.\n"
            "Рис. 4 – Карточка заказа: диагностика и согласование, изменения статуса, прикрепление фотографий устройства и работ.\n"
            "Рис. 5 – Страница SRM-аналитики: сводка по поставщикам, закупкам и нарушениям.\n"
            "Рис. 6 – Страница «Правила»: просмотр активного набора правил (онтологии) и источника правил.\n"
            "Рис. 7 – Страница «Нарушения»: фильтрация по типам, уровням риска и статусу обработки.\n"
            "Рис. 8 – Страница «Запуски анализа»: список запусков, ссылки на отчёты и графики."
        ),
        style_name=base_style,
    )

    p = ps[s32]
    p = _insert_after(
        p,
        (
            "Онтология правил реализована как формализованный JSON-слой, включающий как параметрические настройки "
            "(например, допустимая задержка поставки и пороги рейтинга), так и «rulebook» — список активных правил "
            "с кодом, типом, целевой сущностью, условием, весом, шаблонами объяснений и рекомендаций. "
            "Загрузка и валидация онтологии выполняется модулем `src/srm/ontology/loader.py`."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "Для обеспечения динамической интерпретации правил применяется механизм rulebook: активные правила хранятся в виде "
            "структурированных объектов `RuleDefinition` (код правила, тип, целевая сущность, пороги, вес `weight`, "
            "шаблоны объяснений и рекомендаций). Агенты получают из онтологии только те правила, которые соответствуют их зоне "
            "ответственности (например, BudgetAgent обрабатывает `rule_type=budget`)."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "Интеллектуальный анализ выполнен по мультиагентной схеме. Специализированные агенты-детекторы реализованы в `srm.agents.detectors`, "
            "а их оркестрация — в `srm.agents.composite.CompositeAgent`. Каждый агент применяет только «свои» правила, "
            "возвращает нарушения в унифицированном формате и добавляет объяснение (explainability) и рекомендацию "
            "(rule-based). Объединение и дедупликация выполняются на уровне CompositeAgent."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "Агрегированная оценка риска поставщика реализована в модуле `src/srm/logic/supplier_risk.py` и вычисляется "
            "в диапазоне 0–100 по взвешенной формуле, где веса определяются онтологией:\n"
            "risk_score = min(100,\n"
            "  Wb·budget_score + Wd·delivery_score + Ws·supplier_status_score + Ww·warranty_score + Wr·repeat_violation_score + Wp·price_outlier_score\n"
            ")\n"
            "Интерпретация уровня риска: 0–24 — low, 25–49 — medium, 50–74 — high, 75–100 — critical. "
            "Для объяснимости сохраняются причины (reasons) и вклад компонент (components)."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "Система поддерживает три контура запуска анализа:\n"
            "— CLI: `python -m srm.cli analyze --data ... --rules ... --out ...`;\n"
            "— API: POST `/analyze` с JSON-полезной нагрузкой;\n"
            "— Web: запуск аудита из интерфейса (доступно ролям admin/manager/analyst)."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "При каждом запуске анализа формируются артефакты: JSON-отчёт, графики в формате PNG и лог-файл. "
            "Отчёт дополнительно содержит вычисляемые показатели: финансовые потери и прогнозные вероятности (risk_probability) "
            "для отдельных типов нарушений (вероятность просрочки и превышения бюджета), рассчитанные по простой статистической модели "
            "с учётом истории нарушений и параметров из онтологии (модуль `src/srm/logic/predictions.py`)."
        ),
        style_name=base_style,
    )

    p = ps[s33]
    p = _insert_after(
        p,
        (
            "Тестирование прототипа выполняется с использованием pytest и включает проверку ключевых сценариев: "
            "авторизация, запуск анализа (CLI/API/Web), корректность выявления нарушений, создание отчёта и графиков, "
            "а также работоспособность страниц с пагинацией. Набор тестов расположен в каталоге `tests/`."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "Для верификации на тестовых данных используется демонстрационный набор (базовый и расширенный). "
            "Корректность проверяется по признакам: 1) наличие ожидаемых типов нарушений; 2) заполнение таблицы `violations`; "
            "3) формирование артефактов анализа; 4) доступность результатов в веб-интерфейсе. "
            "Для научной части предусмотрен вычислительный эксперимент сравнения baseline и proposed подходов "
            "с расчётом метрик precision/recall/F1 и сохранением результатов в JSON/CSV/PNG "
            "(команда `python -m srm.cli experiment-risk`)."
        ),
        style_name=base_style,
    )
    p = _insert_after(
        p,
        (
            "Дополнительно реализована готовность к развёртыванию на сервере ВУЗа: "
            "переменные окружения (`.env.example`), скрипты запуска для Linux/Windows (`scripts/run_server.sh`, `scripts/run_server.ps1`), "
            "healthcheck `/health` и readiness `/ready`, а также инструкции развёртывания в `DEPLOYMENT.md`."
        ),
        style_name=base_style,
    )

    # Add a short note about date for reproducibility (kept minimal)
    p = _insert_after(
        p,
        f"Примечание: описанная конфигурация актуальна на дату подготовки отчёта — {date.today().isoformat()}.",
        style_name=base_style,
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT_PATH))
    print(f"Готово: {OUT_PATH}")


if __name__ == "__main__":
    # Ensure consistent UTF-8 I/O for Windows consoles
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
