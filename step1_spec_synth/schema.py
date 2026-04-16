from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TaskType = Literal["display", "form", "list", "detail", "dashboard", "launcher", "unknown"]


class DegradationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["strict", "conservative", "graceful"] = "conservative"
    summary: str = Field(default="")


class UIPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    component_kind: str = Field(min_length=1)
    purpose: str = Field(default="")


class StateFieldDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    field_type: Literal["string", "number", "boolean", "object", "array", "enum", "unknown"] = "unknown"
    default: object | None = None
    required: bool = False
    description: str = Field(default="")


class EventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    trigger: str = Field(min_length=1)
    source_area_id: str = Field(default="")
    handler_goal: str = Field(default="")
    updates_state: list[str] = Field(default_factory=list)
    async_required: bool = False


class DOMRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selector_hint: str = Field(default="")
    element: str = Field(min_length=1)
    purpose: str = Field(default="")
    required: bool = True


class DataRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    source: str = Field(default="")
    shape: str = Field(default="")
    required: bool = False


class AsyncRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    trigger: str = Field(min_length=1)
    success_state: str = Field(default="")
    error_state: str = Field(default="")
    fallback: str = Field(default="")


class ChildGadgetNeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: str = Field(min_length=1)
    purpose: str = Field(default="")
    required_methods: list[str] = Field(default_factory=list)


class AcquisitionNeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acquisition_name: str = Field(min_length=1)
    methods: list[str] = Field(default_factory=list)
    purpose: str = Field(default="")


class AllowedDegradation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition: str = Field(min_length=1)
    fallback: str = Field(min_length=1)


class ComponentSpecDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: TaskType
    page_goal: str = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    degradation_policy: DegradationPolicy = Field(default_factory=DegradationPolicy)
    ui_plan: list[UIPlanItem] = Field(default_factory=list)
    component_whitelist_used: list[str] = Field(default_factory=list)
    state_schema: list[StateFieldDraft] = Field(default_factory=list)
    events: list[EventDraft] = Field(default_factory=list)
    dom_requirements: list[DOMRequirement] = Field(default_factory=list)
    data_requirements: list[DataRequirement] = Field(default_factory=list)
    async_requirements: list[AsyncRequirement] = Field(default_factory=list)
    child_gadget_needs: list[ChildGadgetNeed] = Field(default_factory=list)
    acquisition_needs: list[AcquisitionNeed] = Field(default_factory=list)
    allowed_degradation: list[AllowedDegradation] = Field(default_factory=list)
    todo_markers: list[str] = Field(default_factory=list)


COMPONENT_SPEC_DRAFT_JSON_SCHEMA = ComponentSpecDraft.model_json_schema()


__all__ = ["COMPONENT_SPEC_DRAFT_JSON_SCHEMA", "ComponentSpecDraft", "TaskType"]
