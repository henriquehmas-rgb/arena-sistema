from pydantic import BaseModel, EmailStr, Field

from app.models.enums import PapelStaff


class StaffOut(BaseModel):
    id: int
    nome: str
    email: EmailStr
    papel: PapelStaff
    ativo: bool
    model_config = {"from_attributes": True}


class StaffCriar(BaseModel):
    nome: str
    email: EmailStr
    senha: str = Field(min_length=8)
    papel: PapelStaff


class StaffAtualizar(BaseModel):
    nome: str | None = None
    papel: PapelStaff | None = None
    ativo: bool | None = None
    senha: str | None = Field(default=None, min_length=8)
