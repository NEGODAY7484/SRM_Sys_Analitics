"""Ontology-driven rule engine (dynamic, offline, explainable).

Scientific novelty hook:
- Rules are loaded at runtime from JSON (ontology layer).
- Agents apply only their relevant rule subsets.
- Each triggered rule produces an explainable violation:
  rule_code, compared values, cause, risk_impact, recommendation.

Security note:
We support condition as a string expression, evaluated via a restricted AST evaluator.
No attribute access, no imports, no function definitions.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import date
from typing import Any

from srm.data.models import ProcurementRecord
from srm.logic.violations import Violation, ViolationType
from srm.ontology.models import RuleOntology
from srm.ontology.rulebook import RuleDefinition


@dataclass(frozen=True, slots=True)
class RuleMatch:
    rule: RuleDefinition
    violated: bool
    context: dict[str, Any]
    compared: dict[str, Any]
    explanation: str
    recommendation: str
    risk_level: str


def apply_rules_to_purchase(
    record: ProcurementRecord,
    ontology: RuleOntology,
    *,
    analysis_date: date,
    rules: tuple[RuleDefinition, ...],
) -> list[Violation]:
    """Apply a subset of rules to one purchase record and return violations."""

    out: list[Violation] = []
    for r in rules:
        if not r.is_active:
            continue
        if r.target_entity != "purchase":
            continue
        m = match_rule_purchase(record, ontology, analysis_date=analysis_date, rule=r)
        if not m.violated:
            continue
        vtype = violation_type_for_rule(m.rule)
        out.append(
            Violation(
                procurement_id=record.procurement_id,
                violation_type=vtype,
                message=m.explanation,
                details={
                    "rule_code": m.rule.rule_code,
                    "rule_name": m.rule.rule_name,
                    "rule_type": m.rule.rule_type,
                    "target_entity": m.rule.target_entity,
                    "risk_impact": m.rule.risk_impact,
                    "weight": m.rule.weight,
                    "risk_level": m.risk_level,
                    "cause": m.explanation,
                    "recommendation": m.recommendation,
                    "compared": _jsonable(m.compared),
                    "threshold": _jsonable(m.rule.threshold),
                    "condition": m.rule.condition,
                },
            )
        )
    return out


def match_rule_purchase(
    record: ProcurementRecord,
    ontology: RuleOntology,
    *,
    analysis_date: date,
    rule: RuleDefinition,
) -> RuleMatch:
    ctx = build_purchase_context(
        record, ontology, analysis_date=analysis_date, threshold=rule.threshold
    )
    violated = eval_condition(rule.condition, ctx)
    compared = extract_compared_values(rule.condition, ctx)
    risk_level = risk_level_from_weight(rule.weight)
    explanation = format_template(
        rule.explanation_template, ctx, rule=rule, extra={"risk_level": risk_level}
    )
    recommendation = format_template(
        rule.recommendation_template, ctx, rule=rule, extra={"risk_level": risk_level}
    )
    return RuleMatch(
        rule=rule,
        violated=bool(violated),
        context=ctx,
        compared=compared,
        explanation=explanation,
        recommendation=recommendation,
        risk_level=risk_level,
    )


def build_purchase_context(
    record: ProcurementRecord,
    ontology: RuleOntology,
    *,
    analysis_date: date,
    threshold: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build evaluation context for purchase rules."""

    th = dict(threshold or {})

    total_amount = float(record.contract_amount)
    planned_budget = float(record.planned_budget) if record.planned_budget is not None else None
    tolerance_pct = float(th.get("tolerance_pct", ontology.budget.tolerance_pct or 0.0))
    allowed_delay_days = int(
        th.get("allowed_delay_days", ontology.delivery.allowed_delay_days or 0)
    )
    consider_undelivered = bool(
        th.get(
            "consider_undelivered_as_violation",
            ontology.delivery.consider_undelivered_as_violation,
        )
    )

    due = record.delivery_due_date
    actual = record.delivery_actual_date
    delay_days: int | None = None
    if due is not None:
        if actual is not None:
            delay_days = (actual - due).days
        else:
            if consider_undelivered and analysis_date > due:
                delay_days = (analysis_date - due).days

    overspend = None
    excess_pct = None
    if planned_budget is not None and planned_budget > 0:
        overspend = round(max(0.0, total_amount - planned_budget), 2)
        excess_pct = round(max(0.0, (total_amount / planned_budget - 1.0) * 100.0), 2)

    supplier_rating = _to_float(record.extra.get("supplier_rating"))
    supplier_status = str(record.extra.get("supplier_status") or "")
    supplier_approved = record.extra.get("supplier_approved")
    warranty_months = _to_int(record.extra.get("warranty_months"))
    unit_price = _to_float(record.extra.get("unit_price"))
    category_avg_price = _to_float(record.extra.get("category_avg_price"))
    max_over_avg_pct = float(th.get("max_over_avg_pct", ontology.price.max_over_avg_pct or 0.0))
    over_pct = None
    if unit_price is not None and category_avg_price is not None and category_avg_price > 0:
        over_pct = round(max(0.0, (unit_price / category_avg_price - 1.0) * 100.0), 2)

    min_supplier_rating = float(
        th.get("min_supplier_rating", ontology.risk.min_supplier_rating or 0.0)
    )
    required_min_months = int(
        th.get("required_min_months", ontology.warranty.required_min_months or 0)
    )

    ctx: dict[str, Any] = {
        # record fields (aliases included for expressive rules)
        "procurement_id": record.procurement_id,
        "purchase_id": record.procurement_id,
        "supplier_id": record.supplier_id,
        "supplier_name": record.supplier_name,
        "category": record.category,
        "item": record.item,
        "total_amount": total_amount,
        "contract_amount": total_amount,
        "planned_budget": planned_budget,
        "contract_date": record.contract_date,
        "delivery_due_date": due,
        "delivery_actual_date": actual,
        "analysis_date": analysis_date,
        # ontology + thresholds
        "tolerance_pct": tolerance_pct,
        "allowed_delay_days": allowed_delay_days,
        "consider_undelivered_as_violation": consider_undelivered,
        "min_supplier_rating": min_supplier_rating,
        "required_min_months": required_min_months,
        "max_over_avg_pct": max_over_avg_pct,
        # supplier lists
        "blacklist": set(ontology.suppliers.blacklist),
        "whitelist": set(ontology.suppliers.whitelist)
        if ontology.suppliers.whitelist is not None
        else None,
        # derived features
        "delay_days": delay_days,
        "overspend": overspend,
        "excess_pct": excess_pct,
        "supplier_rating": supplier_rating,
        "supplier_status": supplier_status,
        "supplier_approved": supplier_approved,
        "warranty_months": warranty_months,
        "unit_price": unit_price,
        "category_avg_price": category_avg_price,
        "over_pct": over_pct,
        # helper functions for expressions (whitelisted calls)
        "coalesce": _coalesce,
        "days_between": _days_between,
        "abs": abs,
        "min": min,
        "max": max,
        "len": len,
    }
    return ctx


def eval_condition(condition: str | dict[str, Any], ctx: dict[str, Any]) -> bool:
    if isinstance(condition, dict):
        return eval_json_condition(condition, ctx)
    return bool(safe_eval_bool(condition, ctx))


def eval_json_condition(obj: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """Minimal JSON condition support (optional).

    Supported forms:
    - {"op": ">", "left": "<expr or var>", "right": "<expr or var>"}
    - {"op": "and", "args": [<cond>, <cond>, ...]}
    - {"op": "or", "args": [...]}
    - {"op": "not", "arg": <cond>}
    """

    op = str(obj.get("op") or "").strip().lower()
    if op in {"and", "or"}:
        args = obj.get("args", [])
        if not isinstance(args, list):
            return False
        vals = [eval_condition(a, ctx) if isinstance(a, (str, dict)) else False for a in args]
        return all(vals) if op == "and" else any(vals)
    if op == "not":
        a = obj.get("arg")
        if not isinstance(a, (str, dict)):
            return False
        return not eval_condition(a, ctx)

    left = obj.get("left")
    right = obj.get("right")
    left_value = eval_value(left, ctx)
    right_value = eval_value(right, ctx)
    if op == ">":
        return left_value is not None and right_value is not None and left_value > right_value
    if op == ">=":
        return left_value is not None and right_value is not None and left_value >= right_value
    if op == "<":
        return left_value is not None and right_value is not None and left_value < right_value
    if op == "<=":
        return left_value is not None and right_value is not None and left_value <= right_value
    if op == "==":
        return left_value == right_value
    if op == "!=":
        return left_value != right_value
    if op == "in":
        return left_value in right_value if right_value is not None else False
    if op == "not_in":
        return left_value not in right_value if right_value is not None else False
    return False


def eval_value(expr: Any, ctx: dict[str, Any]) -> Any:
    """Evaluate a JSON value expression."""

    if expr is None:
        return None
    if isinstance(expr, (int, float, str, bool, date)):
        if isinstance(expr, str) and expr.startswith("$"):
            return ctx.get(expr[1:])
        return expr
    if isinstance(expr, dict) and "var" in expr:
        return ctx.get(str(expr["var"]))
    if isinstance(expr, dict) and "mul" in expr:
        args = expr.get("mul")
        if isinstance(args, list) and len(args) == 2:
            a = eval_value(args[0], ctx)
            b = eval_value(args[1], ctx)
            return a * b if a is not None and b is not None else None
    if isinstance(expr, dict) and "add" in expr:
        args = expr.get("add")
        if isinstance(args, list) and len(args) == 2:
            a = eval_value(args[0], ctx)
            b = eval_value(args[1], ctx)
            return a + b if a is not None and b is not None else None
    if isinstance(expr, dict) and "div" in expr:
        args = expr.get("div")
        if isinstance(args, list) and len(args) == 2:
            a = eval_value(args[0], ctx)
            b = eval_value(args[1], ctx)
            if a is None or b in (None, 0):
                return None
            return a / b
    return None


def safe_eval_bool(expr: str, ctx: dict[str, Any]) -> Any:
    """Evaluate a boolean expression using a restricted AST evaluator."""

    tree = ast.parse(expr, mode="eval")
    return _SafeEvaluator(ctx).eval(tree)


def extract_compared_values(condition: str | dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Extract values referenced in expression (for explainability)."""

    if isinstance(condition, dict):
        # Best-effort: return a small snapshot of threshold vars.
        return {
            k: ctx.get(k) for k in ("total_amount", "planned_budget", "delay_days", "supplier_id")
        }

    try:
        tree = ast.parse(condition, mode="eval")
    except Exception:
        return {}
    names = sorted(_extract_names(tree))
    compared: dict[str, Any] = {}
    for n in names:
        if n in ctx and n not in {"coalesce", "days_between", "abs", "min", "max", "len"}:
            compared[n] = _jsonable(ctx.get(n))
    return compared


def _extract_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            names.add(n.id)
    return names


def format_template(
    tpl: str, ctx: dict[str, Any], *, rule: RuleDefinition, extra: dict[str, Any]
) -> str:
    data = dict(ctx)
    data.update(extra)
    data["rule_code"] = rule.rule_code
    data["rule_name"] = rule.rule_name
    return tpl.format_map(_SafeFormatDict(data))


def risk_level_from_weight(weight: float) -> str:
    w = float(weight or 0.0)
    if w >= 0.28:
        return "high"
    if w >= 0.18:
        return "medium"
    return "low"


def violation_type_for_rule(rule: RuleDefinition) -> ViolationType:
    rt = rule.rule_type
    code = rule.rule_code
    if rt == "budget" or code.startswith("BUDGET"):
        return ViolationType.BUDGET_EXCEEDED
    if rt == "supplier_status" or code.startswith("DISALLOWED_SUPPLIER"):
        return ViolationType.DISALLOWED_SUPPLIER
    if rt == "delivery" or code.startswith("DELIVERY"):
        return ViolationType.DELIVERY_DELAY
    if rt == "warranty" or code.startswith("WARRANTY"):
        return ViolationType.MISSING_WARRANTY
    if rt == "price" or code.startswith("PRICE"):
        return ViolationType.PRICE_TOO_HIGH
    if rt == "repeat" or code.startswith("REPEAT"):
        return ViolationType.RECURRING_SUPPLIER_VIOLATIONS
    if rt == "risk" or code.startswith("LOW_SUPPLIER_RATING"):
        return ViolationType.LOW_RATING_SUPPLIER
    return ViolationType.DISALLOWED_SUPPLIER


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "-"


def _coalesce(*args: Any) -> Any:
    for a in args:
        if a not in (None, ""):
            return a
    return None


def _days_between(a: Any, b: Any) -> int | None:
    if not isinstance(a, date) or not isinstance(b, date):
        return None
    return (a - b).days


def _to_float(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except Exception:
        return None


def _to_int(v: Any) -> int | None:
    if v in (None, ""):
        return None
    try:
        return int(v)
    except Exception:
        return None


class _SafeEvaluator:
    """Restricted AST evaluator for expressions."""

    def __init__(self, ctx: dict[str, Any]) -> None:
        self._ctx = ctx

    def eval(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return self.eval(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self._ctx.get(node.id)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
            v = self.eval(node.operand)
            if isinstance(node.op, ast.Not):
                return not bool(v)
            if isinstance(node.op, ast.USub):
                return -v
            if isinstance(node.op, ast.UAdd):
                return +v
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            vals = [self.eval(v) for v in node.values]
            return (
                all(bool(v) for v in vals)
                if isinstance(node.op, ast.And)
                else any(bool(v) for v in vals)
            )
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)
        ):
            a = self.eval(node.left)
            b = self.eval(node.right)
            if a is None or b is None:
                return None
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                return a / b if b != 0 else None
            if isinstance(node.op, ast.Mod):
                return a % b if b != 0 else None
        if isinstance(node, ast.Compare):
            left = self.eval(node.left)
            for op, comp in zip(node.ops, node.comparators, strict=False):
                right = self.eval(comp)
                if isinstance(op, ast.In):
                    ok = left in right if right is not None else False
                elif isinstance(op, ast.NotIn):
                    ok = left not in right if right is not None else False
                elif isinstance(op, ast.Is):
                    ok = left is right
                elif isinstance(op, ast.IsNot):
                    ok = left is not right
                else:
                    if left is None or right is None:
                        ok = False
                    elif isinstance(op, ast.Gt):
                        ok = left > right
                    elif isinstance(op, ast.GtE):
                        ok = left >= right
                    elif isinstance(op, ast.Lt):
                        ok = left < right
                    elif isinstance(op, ast.LtE):
                        ok = left <= right
                    elif isinstance(op, ast.Eq):
                        ok = left == right
                    elif isinstance(op, ast.NotEq):
                        ok = left != right
                    else:
                        ok = False
                if not ok:
                    return False
                left = right
            return True
        if isinstance(node, ast.Call):
            fn = self.eval(node.func)
            if fn not in {
                self._ctx.get("coalesce"),
                self._ctx.get("days_between"),
                self._ctx.get("abs"),
                self._ctx.get("min"),
                self._ctx.get("max"),
                self._ctx.get("len"),
            }:
                raise ValueError("Unsafe function call in rule condition")
            args = [self.eval(a) for a in node.args]
            return fn(*args)

        # Disallow attribute access, subscripts, comprehensions, lambdas, etc.
        raise ValueError("Unsupported expression in rule condition")


def _jsonable(v: Any) -> Any:
    """Convert value to JSON-serializable form (best-effort)."""

    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, set):
        return sorted([_jsonable(x) for x in v])
    if isinstance(v, tuple):
        return [_jsonable(x) for x in v]
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(val) for k, val in v.items()}
    return str(v)
