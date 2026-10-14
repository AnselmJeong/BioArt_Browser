"""Bounded metadata for editable scientific schematics; never executable code."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

HexColor = Annotated[str, Field(pattern=r'^#[a-fA-F0-9]{6}$')]
class Parameters(Strict):
    width: float = Field(ge=40, le=2000)
    height: float = Field(ge=40, le=2000)
    spacing: float = Field(ge=8, le=120)
    thickness: float = Field(ge=8, le=100)
    count: int = Field(ge=2, le=100)
    seed: int = Field(ge=0, le=2147483647)
    color: HexColor
    accent: HexColor

class Generator(Strict):
    type: Literal['generator']
    version: Literal[1]
    id: Literal['membrane','vesicle','cell','receptor','antibody','dna','rna','particles','hydrogel','tube']
    params: Parameters

class Brush(Strict):
    type: Literal['brush']
    version: Literal[1]
    id: Literal['membrane','beads','dna','rna','fiber']
    params: Parameters
    path: str = Field(min_length=1, max_length=100000, pattern=r'^[MmLlHhVvCcSsQqTtAaZz\d.,+\-\seE]+$')

class Equation(Strict):
    type: Literal['equation']
    version: Literal[1]
    latex: str = Field(min_length=1, max_length=2000)
    size: float = Field(ge=8, le=160)
    color: HexColor

class Table(Strict):
    type: Literal['table']
    version: Literal[1]
    cells: list[list[Annotated[str, Field(max_length=200)]]] = Field(min_length=1, max_length=20)
    cellWidth: float = Field(ge=40, le=500)
    rowHeight: float = Field(ge=24, le=200)
    fontSize: float = Field(ge=8, le=60)
    header: bool
    color: HexColor
    accent: HexColor

    @model_validator(mode='after')
    def check(self):
        cols=len(self.cells[0])
        if not 1 <= cols <= 12 or any(len(row)!=cols for row in self.cells):
            raise ValueError('Table must be rectangular with 1-12 columns')
        return self

class Panels(Strict):
    type: Literal['panels']
    version: Literal[1]
    rows: int = Field(ge=1, le=12)
    columns: int = Field(ge=1, le=12)
    panelWidth: float = Field(ge=100, le=1500)
    panelHeight: float = Field(ge=100, le=1500)
    gap: float = Field(ge=0, le=200)
    startLabel: str = Field(pattern=r'^[A-Z]$')
    color: HexColor

    @model_validator(mode='after')
    def check(self):
        if self.rows*self.columns>12: raise ValueError('At most 12 panels')
        return self

class Inset(Strict):
    type: Literal['inset']
    version: Literal[1]
    sourceId: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    live: bool
    centerX: float = Field(ge=0, le=1)
    centerY: float = Field(ge=0, le=1)
    span: float = Field(ge=.1, le=1)
    size: float = Field(ge=80, le=1000)
    shape: Literal['circle','rect']
    color: HexColor

Science = Annotated[Generator | Brush | Equation | Table | Panels | Inset, Field(discriminator='type')]
