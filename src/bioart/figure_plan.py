"""Strict model boundary: the agent proposes coordinates, never executable SVG."""
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AssetPlacement(StrictModel):
    file_id: str
    x: float = Field(ge=0, le=1400)
    y: float = Field(ge=0, le=850)
    width: float = Field(ge=20, le=1400)
    height: float = Field(ge=20, le=800)
    label: str = Field(max_length=80)


class FigureArrow(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    x1: float = Field(ge=0, le=1400)
    y1: float = Field(ge=0, le=850)
    x2: float = Field(ge=0, le=1400)
    y2: float = Field(ge=0, le=850)
    label: str = Field(max_length=50)


class FigureText(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    x: float = Field(ge=0, le=1400)
    y: float = Field(ge=20, le=850)
    text: str = Field(max_length=100)
    font_size: float = Field(ge=12, le=36)


class FigurePlan(StrictModel):
    title: str = Field(max_length=65)
    explanation: str = Field(max_length=2500)
    objects: list[AssetPlacement] = Field(min_length=1, max_length=8)
    arrows: list[FigureArrow] = Field(max_length=24)
    texts: list[FigureText] = Field(max_length=24)
