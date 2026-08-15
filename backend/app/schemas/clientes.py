from pydantic import BaseModel, EmailStr


class ClienteOut(BaseModel):
    id: int
    nome: str
    email: EmailStr
    celular: str
    cpf: str | None = None
    model_config = {"from_attributes": True}


class ClienteAdminCriar(BaseModel):
    nome: str
    email: EmailStr
    celular: str
    cpf: str | None = None


class ClienteMeAtualizar(BaseModel):
    nome: str
    celular: str
