"""Pydantic v2 domain models shared by the three platform domains."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TEMPLATE_VAR = re.compile(r"\$\{([A-Z_]+)\}")
TAG_PATTERN = re.compile(r"^[\w\u4e00-\u9fff-]{1,64}$")
RESERVED_TAGS = {"and", "or"}
ALLOWED_TEMPLATE_VARS = {"SCENARIO_URI", "OUTPUT_DIR", "SEED", "LOG_DIR"}
ALLOWED_ENV_KEYS = {
    "SIM_SEED",
    "LOG_LEVEL",
    "SCENARIO_ID",
    "TASK_ID",
    "CASE_RUN_ID",
    "SIM_ENGINE",
    "METRIC_CONFIG",
}
LEVELS = {"S0", "S1", "S2"}


class ScenarioSource(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["record", "synthetic"] = "record"
    log_id: str = ""
    log_uri: str = ""
    log_checksum: str = ""
    format: Literal["rsclbag", "mcap", "bag", "parquet"] = "rsclbag"

    @model_validator(mode="before")
    @classmethod
    def drop_extract(cls, value: Any) -> Any:
        if isinstance(value, dict) and "extract" in value:
            return {key: item for key, item in value.items() if key != "extract"}
        return value


class TimeWindow(BaseModel):
    start_ts: int = 0
    end_ts: int = 0
    trigger_ts: int = 0

    @model_validator(mode="after")
    def ordered(self) -> TimeWindow:
        if not (self.start_ts <= self.trigger_ts <= self.end_ts):
            raise ValueError("时间窗必须满足 start_ts ≤ trigger_ts ≤ end_ts")
        return self


class EnvValue(BaseModel):
    model_config = ConfigDict(extra="allow")
    field_name: str
    value: str = ""
    is_number: bool = False
    unit: str = ""


class RuleFunction(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = ""
    function_field_name: str = ""
    template_id: str
    env: dict[str, EnvValue]


class MetricConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    trigger_functions: list[RuleFunction] = Field(default_factory=list)
    trigger_ops: list[Literal["AND", "OR"]] = Field(default_factory=list)
    functions: list[RuleFunction] = Field(default_factory=list)
    ops: list[Literal["AND", "OR"]] = Field(default_factory=list)
    ret: Literal["pass", "fail"] = "pass"
    action: str = "not_stop_sim"
    level: str = "S0"
    is_global: bool = False

    @field_validator("level")
    @classmethod
    def valid_level(cls, value: str) -> str:
        if value not in LEVELS:
            raise ValueError(f"level 必须是 {sorted(LEVELS)} 之一")
        return value


class ScenarioMetricInstance(BaseModel):
    model_config = ConfigDict(extra="allow")
    metric_def_id: str
    metric_def_ver: int = 1
    alias: str | None = None
    config: MetricConfig
    enabled: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)


class ScenarioMetric(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    desc: str = ""
    business_type: str = "dpc"
    run_mode: Literal["async", "sync"] = "async"
    level: str = "S0"
    is_global: bool = False
    trigger_functions: list[RuleFunction] = Field(default_factory=list)
    trigger_ops: list[Literal["AND", "OR"]] = Field(default_factory=list)
    functions: list[RuleFunction] = Field(default_factory=list)
    ops: list[Literal["AND", "OR"]] = Field(default_factory=list)
    ret: Literal["pass", "fail"] = "pass"
    action: str = "not_stop_sim"

    @field_validator("level")
    @classmethod
    def valid_level(cls, value: str) -> str:
        if value not in LEVELS:
            raise ValueError(f"level 必须是 {sorted(LEVELS)} 之一")
        return value


class Scenario(BaseModel):
    model_config = ConfigDict(extra="allow")
    scenario_id: str
    name: str
    version: int = 1
    source: ScenarioSource
    time_window: TimeWindow
    metrics: list[ScenarioMetric] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
    project: str = "default"
    owner: str = ""
    status: Literal["active", "archived"] = "active"
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""


class SetMember(BaseModel):
    scenario_id: str
    scenario_version: int
    sort_order: int = 0


class ScenarioSet(BaseModel):
    model_config = ConfigDict(extra="allow")
    set_id: str
    version: int = 1
    name: str
    description: str = ""
    frozen: bool = False
    owner: str = ""
    project: str = "default"
    members: list[SetMember] = Field(default_factory=list)
    checksum_self: str = ""


class ResourceSpec(BaseModel):
    cpu: int = Field(default=1, ge=0, le=128)
    mem_gb: int = Field(default=1, ge=0, le=1024)
    gpu: int = Field(default=0, ge=0, le=16)


def _default_retry_events() -> list[Literal["timeout", "worker_lost"]]:
    return ["timeout", "worker_lost"]


class RetryPolicy(BaseModel):
    max: int = Field(default=0, ge=0, le=10)
    on: list[Literal["timeout", "worker_lost"]] = Field(default_factory=_default_retry_events)


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    binary_id: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    resource: ResourceSpec = Field(default_factory=ResourceSpec)
    timeout_sec: int = Field(default=600, ge=1, le=86400)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)

    @field_validator("args")
    @classmethod
    def safe_args(cls, args: list[str]) -> list[str]:
        for arg in args:
            for match in TEMPLATE_VAR.findall(arg):
                if match not in ALLOWED_TEMPLATE_VARS:
                    raise ValueError(f"args 模板变量未获白名单批准：{match}")
        return args

    @field_validator("env")
    @classmethod
    def safe_env(cls, env: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(env) - ALLOWED_ENV_KEYS)
        if unknown:
            raise ValueError(f"env key 不在白名单：{unknown}")
        return env


class TaskBatch(BaseModel):
    max_cases: int = Field(default=0, ge=0)
    shard_size: int = Field(default=1000, ge=1, le=10000)


class SimTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str | None = None
    name: str = ""
    project: str | None = None
    owner: str | None = None
    set_id: str
    set_version: int | None = None
    runtime: RuntimeConfig
    priority: int = Field(default=5, ge=0, le=9)
    batch: TaskBatch = Field(default_factory=TaskBatch)
    metrics: list[str] = Field(default_factory=list)
    seed: int | None = None
    dedup: bool = True


class TaskControl(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    reason: str = ""


class CaseRunView(BaseModel):
    case_run_id: str
    task_id: str
    scenario_id: str
    scenario_version: int
    status: str
    attempt: int
    worker_id: str | None = None
    exit_code: int | None = None
    output_uri: str | None = None
    reason: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class MetricCategory(BaseModel):
    id: str
    name: str
    sort_order: int = 0
    description: str = ""


class MetricType(BaseModel):
    id: str
    category_id: str
    parent_id: str | None = None
    name: str
    sort_order: int = 0
    description: str = ""
    status: str = "active"


class MetricTemplate(BaseModel):
    id: str
    name: str
    kind: Literal["trigger", "function"]
    env_schema: dict[str, Any]
    env_example: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"
    description: str = ""


class TemplateRef(BaseModel):
    template_id: str
    slot: int = 0
    required: bool = True


class MetricDef(BaseModel):
    id: str = ""
    version: int = 1
    type_id: str
    name: str
    level: str = "S0"
    business_type: str = "dpc"
    run_mode: Literal["async", "sync"] = "async"
    is_global: bool = False
    trigger_templates: list[TemplateRef] = Field(default_factory=list)
    trigger_functions: list[RuleFunction] = Field(default_factory=list)
    trigger_ops: list[Literal["AND", "OR"]] = Field(default_factory=list)
    function_templates: list[TemplateRef] = Field(default_factory=list)
    functions: list[RuleFunction] = Field(default_factory=list)
    ops: list[Literal["AND", "OR"]] = Field(default_factory=list)
    ret: Literal["pass", "fail"] = "pass"
    action: str = "not_stop_sim"
    status: str = "active"
    description: str = ""

    @model_validator(mode="after")
    def derive_template_refs(self) -> MetricDef:
        if self.trigger_functions and not self.trigger_templates:
            self.trigger_templates = [
                TemplateRef(template_id=item.template_id, slot=index, required=True)
                for index, item in enumerate(self.trigger_functions)
            ]
        if self.functions and not self.function_templates:
            self.function_templates = [
                TemplateRef(template_id=item.template_id, slot=index, required=True)
                for index, item in enumerate(self.functions)
            ]
        return self


class DataSourceCreate(BaseModel):
    source_id: str | None = None
    kind: Literal["record", "sim_output"] = "record"
    uri: str
    format: Literal["mcap", "bag", "parquet", "dir", "json"] = "mcap"
    project: str | None = None
    duration_ms: int = 0
    channels: list[dict[str, Any]] = Field(default_factory=list)


class ExtractRequest(BaseModel):
    uri: str
    format: Literal["mcap", "bag", "parquet", "dir", "json"] = "mcap"
    project: str | None = None


class ScenarioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    source: ScenarioSource
    time_window: TimeWindow
    metrics: list[ScenarioMetric] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
    project: str | None = None

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, value: list[str]) -> list[str]:
        for tag in value:
            if tag.lower() in RESERVED_TAGS:
                raise ValueError(f"标签 {tag!r} 是保留字，不能使用 AND/OR")
            if not TAG_PATTERN.fullmatch(tag):
                raise ValueError(
                    f"标签 {tag!r} 含非法字符；仅允许中文、字母、数字、下划线和短横线"
                )
        return value


class ScenarioUpdate(ScenarioCreate):
    version: int = Field(ge=1)
    change_note: str = ""


class SetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    members: list[SetMember] = Field(default_factory=list)
    project: str | None = None
    visibility: Literal["private", "public"] = "private"


class SetUpdate(SetCreate):
    version: int = Field(ge=1)
    change_note: str = ""


class SetDerive(BaseModel):
    name: str | None = None
    project: str | None = None
    visibility: Literal["private", "public"] | None = None
