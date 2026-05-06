"""Rule-based recommendations for violations and supplier risks.

No ML/LLM is used; recommendations are deterministic and explainable.
"""

from __future__ import annotations

from srm.logic.violations import ViolationType


def recommendation_for_violation(v_type: str) -> str:
    mapping: dict[str, str] = {
        ViolationType.BUDGET_EXCEEDED.value: "Пересогласовать бюджет или уменьшить объём закупки; проверить лимиты по категории.",
        ViolationType.DISALLOWED_SUPPLIER.value: "Проверить статус поставщика; при необходимости заменить на одобренного и провести ручную проверку документов/качества.",
        ViolationType.DELIVERY_DELAY.value: "Связаться с поставщиком и зафиксировать новый срок; при систематических просрочках снизить рейтинг или ограничить закупки.",
        ViolationType.LOW_RATING_SUPPLIER.value: "Ограничить закупки у поставщика и запросить подтверждение качества/гарантии; рассмотреть альтернативы.",
        ViolationType.MISSING_WARRANTY.value: "Запросить гарантийные условия/документы; не использовать запчасть в заказе без согласования.",
        ViolationType.PRICE_TOO_HIGH.value: "Проверить рыночную цену и среднюю по категории; запросить скидку или заменить поставщика/позицию.",
        ViolationType.RECURRING_SUPPLIER_VIOLATIONS.value: "Провести аудит поставщика и условий; при превышении порога нарушений временно ограничить закупки.",
    }
    return mapping.get(v_type, "Требуется ручная проверка и корректирующие действия.")


def recommendation_for_risk_level(level: str) -> str:
    if level == "critical":
        return "Рекомендуется немедленно ограничить закупки и вынести поставщика на рассмотрение руководителя."
    if level == "high":
        return "Рекомендуется подготовить план корректирующих действий и усилить контроль закупок/сроков."
    if level == "medium":
        return "Рекомендуется мониторинг и точечные корректировки условий поставки/гарантии."
    return "Рекомендуется мониторинг в штатном режиме."
