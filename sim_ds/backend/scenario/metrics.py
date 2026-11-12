"""Five-layer metric validation (structural + template env_schema)."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.models import MetricConfig, MetricDef, ScenarioMetricInstance
from backend.shared.canonical import canonical_json
from backend.shared.errors import AppError

MAX_CONFIG_BYTES = 16 * 1024


def _invalid(path: str, message: str) -> AppError:
    return AppError(
        "METRIC_CONFIG_INVALID",
        "Metric 配置校验失败",
        status=422,
        detail={"path": path, "reason": message},
    )


def validate_structure(config: MetricConfig) -> None:
    if not config.functions:
        raise _invalid("$.functions", "至少需要一个检测函数")
    for index, item in enumerate(config.trigger_functions):
        if not item.template_id:
            raise _invalid(f"$.trigger_functions[{index}].template_id", "template_id 不能为空")
        if not item.env:
            raise _invalid(f"$.trigger_functions[{index}].env", "env 不能为空")
    for index, item in enumerate(config.functions):
        if not item.template_id:
            raise _invalid(f"$.functions[{index}].template_id", "template_id 不能为空")
        if not item.env:
            raise _invalid(f"$.functions[{index}].env", "env 不能为空")
    if not config.action.strip():
        raise _invalid("$.action", "action 不能为空")
    size = len(canonical_json(config.model_dump()).encode("utf-8"))
    if size > MAX_CONFIG_BYTES:
        raise _invalid("$", f"config 超过 {MAX_CONFIG_BYTES} 字节，请拆分为 alias")


async def _load_template(session: AsyncSession, template_id: str) -> dict[str, Any]:
    row = (
        await session.execute(
            text("SELECT id, kind, env_schema, status FROM metric_template WHERE id = :id"),
            {"id": template_id},
        )
    ).mappings().first()
    if row is None:
        raise _invalid("$.template_id", f"template_id {template_id} 不存在")
    data = dict(row)
    if data["status"] != "active":
        raise _invalid("$.template_id", f"template_id {template_id} 已废弃")
    return data


def _validate_env(template: dict[str, Any], env: Any, path: str) -> None:
    validator = Draft202012Validator(template["env_schema"])
    payload = {
        key: (value.model_dump() if hasattr(value, "model_dump") else value)
        for key, value in env.items()
    } if isinstance(env, dict) else env
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    for error in errors:
        location = path + "".join(f"[{part}]" for part in error.path)
        raise _invalid(location, error.message)


async def validate_instance(session: AsyncSession, instance: ScenarioMetricInstance) -> None:
    validate_structure(instance.config)
    config = instance.config
    for index, item in enumerate(config.trigger_functions):
        template = await _load_template(session, item.template_id)
        if template["kind"] != "trigger":
            raise _invalid(
                f"$.trigger_functions[{index}].template_id",
                f"template {item.template_id} 不是 trigger 类型",
            )
        _validate_env(template, item.env, f"$.trigger_functions[{index}].env")
    for index, item in enumerate(config.functions):
        template = await _load_template(session, item.template_id)
        if template["kind"] != "function":
            raise _invalid(
                f"$.functions[{index}].template_id",
                f"template {item.template_id} 不是 function 类型",
            )
        _validate_env(template, item.env, f"$.functions[{index}].env")


async def validate_def_templates(session: AsyncSession, definition: MetricDef) -> None:
    for ref in definition.trigger_templates:
        template = await _load_template(session, ref.template_id)
        if template["kind"] != "trigger":
            raise _invalid("$.trigger_templates", f"template {ref.template_id} 必须是 trigger")
    for ref in definition.function_templates:
        template = await _load_template(session, ref.template_id)
        if template["kind"] != "function":
            raise _invalid("$.function_templates", f"template {ref.template_id} 必须是 function")


def validate_required_templates(definition: MetricDef, config: MetricConfig) -> None:
    trigger_ids = {item.template_id for item in config.trigger_functions}
    function_ids = {item.template_id for item in config.functions}
    for ref in definition.trigger_templates:
        if ref.required and ref.template_id not in trigger_ids:
            raise _invalid("$.trigger_functions", f"缺少必需 trigger 模板 {ref.template_id}")
    for ref in definition.function_templates:
        if ref.required and ref.template_id not in function_ids:
            raise _invalid("$.functions", f"缺少必需 function 模板 {ref.template_id}")
