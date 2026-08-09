"use client";

// Admin — CRUD de equipe (staff). Task T12 Step 5.

import { useEffect, useState, type CSSProperties } from "react";
import { api } from "@/lib/api";
import { mensagemErro } from "@/lib/auth";
import { Botao, BotaoSecundario, Campo, Card, Titulo, Aviso } from "@/components/ui";

type Staff = { id: number; nome: string; email: string; papel: string; ativo: boolean };

const PAPEIS = [
  { valor: "admin", label: "Admin" },
  { valor: "atendente", label: "Atendente" },
];

const tableStyle: CSSProperties = { width: "100%", borderCollapse: "collapse", marginTop: 4 };
const thStyle: CSSProperties = {
  textAlign: "left",
  padding: "8px 10px",
  borderBottom: "2px solid #e7e9f0",
  fontSize: "0.78rem",
  color: "var(--cinza)",
  textTransform: "uppercase",
};
const tdStyle: CSSProperties = { padding: "10px", borderBottom: "1px solid #eef0f5", verticalAlign: "middle" };

export default function EquipePage() {
  const [equipe, setEquipe] = useState<Staff[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [salvandoId, setSalvandoId] = useState<number | null>(null);

  const [mostrarForm, setMostrarForm] = useState(false);
  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [papel, setPapel] = useState("atendente");
  const [enviando, setEnviando] = useState(false);
  const [erroForm, setErroForm] = useState<string | null>(null);

  useEffect(() => {
    carregar();
  }, []);

  async function carregar() {
    setErro(null);
    try {
      const lista = (await api.equipe.listar()) as Staff[];
      setEquipe(lista);
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível carregar a equipe."));
    }
  }

  async function criar(e: React.FormEvent) {
    e.preventDefault();
    setErroForm(null);
    setEnviando(true);
    try {
      await api.equipe.criar({ nome, email, senha, papel });
      setNome("");
      setEmail("");
      setSenha("");
      setPapel("atendente");
      setMostrarForm(false);
      await carregar();
    } catch (e) {
      setErroForm(mensagemErro(e, "Não foi possível cadastrar o integrante da equipe."));
    } finally {
      setEnviando(false);
    }
  }

  async function alterarPapel(s: Staff, papel: string) {
    setSalvandoId(s.id);
    setErro(null);
    try {
      await api.equipe.atualizar(s.id, { papel });
      await carregar();
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível alterar o papel."));
    } finally {
      setSalvandoId(null);
    }
  }

  async function alternarAtivo(s: Staff) {
    const acao = s.ativo ? "desativar" : "reativar";
    if (!window.confirm(`Tem certeza que deseja ${acao} ${s.nome}?`)) return;
    setSalvandoId(s.id);
    setErro(null);
    try {
      await api.equipe.atualizar(s.id, { ativo: !s.ativo });
      await carregar();
    } catch (e) {
      setErro(mensagemErro(e, "Não foi possível atualizar o status."));
    } finally {
      setSalvandoId(null);
    }
  }

  if (equipe === null && !erro) return <p>Carregando...</p>;

  return (
    <>
      <Titulo>Equipe</Titulo>
      {erro && <Aviso tipo="erro">{erro}</Aviso>}

      <div style={{ marginBottom: 16 }}>
        <Botao onClick={() => setMostrarForm((v) => !v)}>{mostrarForm ? "Fechar" : "+ Novo integrante"}</Botao>
      </div>

      {mostrarForm && (
        <Card style={{ marginBottom: 24, maxWidth: 480 }}>
          <Titulo as="h2">Novo integrante</Titulo>
          {erroForm && <Aviso tipo="erro">{erroForm}</Aviso>}
          <form onSubmit={criar}>
            <Campo label="Nome" value={nome} onChange={(e) => setNome(e.target.value)} required />
            <Campo label="E-mail" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            <Campo
              label="Senha provisória"
              type="password"
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              required
            />
            <div className="ac-campo">
              <label>Papel</label>
              <select className="ac-input" value={papel} onChange={(e) => setPapel(e.target.value)}>
                {PAPEIS.map((p) => (
                  <option key={p.valor} value={p.valor}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
            <Botao type="submit" disabled={enviando}>
              {enviando ? "Salvando..." : "Cadastrar"}
            </Botao>
          </form>
        </Card>
      )}

      {equipe !== null && equipe.length === 0 && <p>Nenhum integrante cadastrado.</p>}

      {equipe !== null && equipe.length > 0 && (
        <Card>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Nome</th>
                <th style={thStyle}>E-mail</th>
                <th style={thStyle}>Papel</th>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Ações</th>
              </tr>
            </thead>
            <tbody>
              {equipe.map((s) => (
                <tr key={s.id} style={!s.ativo ? { opacity: 0.55 } : undefined}>
                  <td style={tdStyle}>{s.nome}</td>
                  <td style={tdStyle}>{s.email}</td>
                  <td style={tdStyle}>
                    <select
                      className="ac-input"
                      value={s.papel}
                      onChange={(e) => alterarPapel(s, e.target.value)}
                      disabled={salvandoId === s.id}
                    >
                      {PAPEIS.map((p) => (
                        <option key={p.valor} value={p.valor}>
                          {p.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td style={tdStyle}>{s.ativo ? "Ativo" : "Inativo"}</td>
                  <td style={tdStyle}>
                    <BotaoSecundario onClick={() => alternarAtivo(s)} disabled={salvandoId === s.id}>
                      {s.ativo ? "Desativar" : "Reativar"}
                    </BotaoSecundario>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
