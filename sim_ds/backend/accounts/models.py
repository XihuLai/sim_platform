"""Account request/response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["super_admin", "admin", "user"]
Status = Literal["active", "disabled"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=256)
    display_name: str = ""
    role: Role = "user"
    project: str = "default"
    max_priority: int = Field(default=5, ge=0, le=9)
    max_daily_cases: int | None = Field(default=None, ge=1)
    max_running_cases: int | None = Field(default=None, ge=1)
    max_cpu: int | None = Field(default=None, ge=1)
    max_mem_gb: int | None = Field(default=None, ge=1)
    max_gpu: int | None = Field(default=None, ge=0)


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=256)
    display_name: str | None = None
    role: Role | None = None
    status: Status | None = None
    project: str | None = None
    max_priority: int | None = Field(default=None, ge=0, le=9)
    max_daily_cases: int | None = Field(default=None, ge=1)
    max_running_cases: int | None = Field(default=None, ge=1)
    max_cpu: int | None = Field(default=None, ge=1)
    max_mem_gb: int | None = Field(default=None, ge=1)
    max_gpu: int | None = Field(default=None, ge=0)


class UserView(BaseModel):
    id: str
    username: str
    display_name: str
    role: Role
    status: Status
    project: str
    max_priority: int
    max_daily_cases: int | None
    max_running_cases: int | None
    max_cpu: int | None
    max_mem_gb: int | None
    max_gpu: int | None
    created_at: str | None
    updated_at: str | None
