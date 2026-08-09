from pydantic import BaseModel, EmailStr, Field


class ClienteCadastro(BaseModel):
    nome: str
    email: EmailStr
    senha: str = Field(min_length=8)
    celular: str


class Login(BaseModel):
    email: EmailStr
    senha: str


class TokenOut(BaseModel):
    access_token: str
    papel: str | None = None


class ClienteCadastroResumo(BaseModel):
    id: int
    nome: str
    email: EmailStr
    model_config = {"from_attributes": True}


class ClienteCadastroOut(BaseModel):
    cliente: ClienteCadastroResumo
    access_token: str


class RecuperarIn(BaseModel):
    email: EmailStr


class RedefinirIn(BaseModel):
    token: str
    senha: str = Field(min_length=8)
