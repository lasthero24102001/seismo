from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer

from .services.parsing import parse_decimal, parse_time


def _num_out(v):
    return None if v is None else float(v)


def _time_out(t):
    return None if t is None else f"{t:%H:%M:%S}.{t.microsecond // 100000}"


def _num_in(v):
    if v in ("", None):
        return None
    return parse_decimal(v)


def _time_in(v):
    if v in ("", None):
        return None
    return parse_time(v)


Num = Annotated[Decimal | None, BeforeValidator(_num_in), PlainSerializer(_num_out, return_type=float | None)]
Tm = Annotated[time | None, BeforeValidator(_time_in), PlainSerializer(_time_out, return_type=str | None)]
Role = Literal["admin", "operator", "viewer"]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    full_name: str | None
    role: str
    is_active: bool = True
    created_at: datetime | None = None
    last_login_at: datetime | None = None


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=128)
    role: Role = "viewer"


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=128)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=128)


class StationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str | None
    aliases: list[str]
    is_active: bool


class StationStats(StationOut):
    events_count: int = 0
    flagged_count: int = 0
    first_date: date | None = None
    last_date: date | None = None


class StationCreate(BaseModel):
    code: str = Field(min_length=2, max_length=8, pattern=r"^[A-Za-z][A-Za-z0-9]+$")
    name: str | None = Field(default=None, max_length=128)
    aliases: list[str] = []


class StationUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    aliases: list[str] | None = None
    is_active: bool | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    station_code: str
    station_name: str | None = None
    source_no: int | None
    event_date: date
    p_phase: str | None
    p_time: Tm
    s_phase: str | None
    s_time: Tm
    origin_time: Tm
    s_minus_p: Num
    r_km: Num
    amp_p: Num
    amp_s: Num
    mb: Num
    ml: Num
    ep_vp: Num
    ep_vs: Num
    ep_vp_vs: Num
    needs_review: bool
    review_reasons: list[str]
    review_comment: str | None = None


class EventDetail(EventOut):
    file_id: int | None
    file_name: str | None = None
    source_row: int | None
    raw: list | dict | None
    record_hash: str
    created_at: datetime
    updated_at: datetime | None


class EventUpdate(BaseModel):
    event_date: date | None = None
    p_phase: str | None = Field(default=None, max_length=8)
    s_phase: str | None = Field(default=None, max_length=8)
    p_time: Tm = None
    s_time: Tm = None
    origin_time: Tm = None
    s_minus_p: Num = Field(default=None, ge=0)
    r_km: Num = Field(default=None, ge=0)
    amp_p: Num = Field(default=None, ge=0)
    amp_s: Num = Field(default=None, ge=0)
    mb: Num = None
    ml: Num = None
    ep_vp: Num = None
    ep_vs: Num = None
    ep_vp_vs: Num = None
    needs_review: bool | None = None
    review_comment: str | None = Field(default=None, max_length=1000)


class Page(BaseModel):
    items: list[EventOut]
    total: int
    page: int
    page_size: int
