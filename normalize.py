# -*- coding: utf-8 -*-
"""
normalize.py
Converte linhas cruas da planilha de teste (colunas em portugues, texto livre,
categorias fora do dominio) em Participant records com o schema canonico do
Dossie Mestre (secao 5 e 8.1).

Este modulo cobre o papel do "parser simples por keywords" citado na secao 10
(FALLBACK - LLM indisponivel): nenhuma chamada de IA e usada aqui, apenas
normalizacao deterministica auditavel.
"""
from __future__ import annotations
import csv
import re
import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Vocabularios canonicos (secao 8.1 / 11.1 do dossie)
# ---------------------------------------------------------------------------

FUNCTIONS = ["Strategy", "Operations", "Technology/Data", "Finance",
             "Marketing/Sales", "People/HR", "Risk/Legal", "Other"]

INDUSTRIES = ["Financial Services", "Consumer/Retail", "Industrial/Manufacturing",
              "Technology", "Healthcare", "Energy", "Professional Services", "Other"]

MATURITY_ORDER = {"Exploring": 0, "Piloting": 1, "Scaling": 2, "Embedded/Transforming": 3}

INTEREST_TAGS = ["Scaling/Value", "Workflow Redesign", "Data/Tech", "Operations",
                  "Agents", "Governance/Risk", "People/Talent", "Growth/Commercial",
                  "Strategy"]

# next_activity canonico (secao 3)
NEXT_ACTIVITY_MAP = {
    "o futuro das operacoes": "Future of Operations",
    "a reinvencao do comercio": "Reinvention of Commerce",
    "como agentes de ia estao redefinindo os servicos financeiros": "Future of Financial Services",
    "nao tenho nenhum interesse em particular": "Networking Lunch",
}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _norm(s: str) -> str:
    return _strip_accents(s or "").strip().lower()


# Mapeamento heuristico de funcao/area em texto livre (PT/EN) -> categoria canonica.
# ORDEM IMPORTA: primeiro match (substring) vence.
_FUNCTION_KEYWORDS = [
    ("technology/data", "Technology/Data"),
    ("machine learning", "Technology/Data"),
    ("dados", "Technology/Data"),
    ("data", "Technology/Data"),
    ("finance", "Finance"),
    ("financeir", "Finance"),
    ("investment banking", "Finance"),
    ("modelagem financeira", "Finance"),
    ("operations", "Operations"),
    ("operac", "Operations"),
    ("supply chain", "Operations"),
    ("suprimentos", "Operations"),
    ("projetos", "Operations"),
    ("civil", "Operations"),
    ("estrutural", "Operations"),
    ("strategy", "Strategy"),
    ("estrateg", "Strategy"),
    ("consult", "Strategy"),
    ("business consult", "Strategy"),
    ("inovacao", "Strategy"),
    ("marketing/sales", "Marketing/Sales"),
    ("marketing", "Marketing/Sales"),
    ("sales", "Marketing/Sales"),
    ("eventos", "Marketing/Sales"),
    ("people/hr", "People/HR"),
    ("recrutamento", "People/HR"),
    ("rh", "People/HR"),
    ("risk/legal", "Risk/Legal"),
    ("risco", "Risk/Legal"),
    ("legal", "Risk/Legal"),
    ("reestruturacao", "Risk/Legal"),
    ("product manager", "Technology/Data"),
]

_INDUSTRY_KEYWORDS = [
    ("financial services", "Financial Services"),
    ("investment banking", "Financial Services"),
    ("private equity", "Financial Services"),
    ("midia e dados financeiros", "Financial Services"),
    ("midia e informacao financeira", "Financial Services"),
    ("gestao de ativos", "Financial Services"),
    ("consumer/retail", "Consumer/Retail"),
    ("varejo", "Consumer/Retail"),
    ("industrial/manufacturing", "Industrial/Manufacturing"),
    ("infraestrutura", "Industrial/Manufacturing"),
    ("construcao", "Industrial/Manufacturing"),
    ("engenharia", "Industrial/Manufacturing"),
    ("mobilidade", "Industrial/Manufacturing"),
    ("transporte", "Industrial/Manufacturing"),
    ("logistica", "Industrial/Manufacturing"),
    ("supply chain", "Industrial/Manufacturing"),
    ("technology", "Technology"),
    ("edtech", "Technology"),
    ("educacao digital", "Technology"),
    ("healthcare", "Healthcare"),
    ("energy", "Energy"),
    ("saneamento", "Energy"),
    ("professional services", "Professional Services"),
    ("feiras de recrutamento", "Professional Services"),
    ("consultoria universitaria", "Professional Services"),
    ("turnaround", "Professional Services"),
    ("restructuring", "Professional Services"),
]


def map_keyword(raw: str, table, canonical_set) -> str:
    """Mapeia texto livre para categoria canonica via substring match; 'Other' se nao achar."""
    n = _norm(raw)
    if n in {_norm(c) for c in canonical_set}:
        # ja e canonico
        for c in canonical_set:
            if _norm(c) == n:
                return c
    for kw, canon in table:
        if kw in n:
            return canon
    return "Other"


def map_next_activity(raw: str) -> list[str]:
    """Retorna lista de next_activity canonicos citados (pode ser multi-select)."""
    if not raw:
        return ["Networking Lunch"]
    parts = [p.strip() for p in raw.split(",")]
    out = []
    for p in parts:
        key = _norm(p)
        mapped = NEXT_ACTIVITY_MAP.get(key)
        if mapped and mapped not in out:
            out.append(mapped)
    if not out:
        out = ["Networking Lunch"]
    return out


def map_axis(raw: str) -> tuple[int, bool]:
    """Converte escala 1..5 (ou 'null') para ordinal -2..+2. Retorna (valor, is_missing)."""
    if raw is None:
        return 0, True
    r = raw.strip().lower()
    if r in ("", "null", "none", "nan"):
        return 0, True
    try:
        v = int(float(r))
    except ValueError:
        return 0, True
    v = max(1, min(5, v))
    return v - 3, False  # 1->-2, 2->-1, 3->0, 4->+1, 5->+2


# Keywords simples para extrair semantic_tags do desafio aberto (fallback sem LLM, secao 10)
_CHALLENGE_KEYWORDS = {
    "Scaling/Value": ["escal", "scal", "valor", "roi", "value"],
    "Workflow Redesign": ["redesenh", "processo", "workflow", "fluxo"],
    "Data/Tech": ["dados", "arquitetura", "data", "modelo", "algoritmo", "predit"],
    "Operations": ["operac", "logistic", "supply", "rota", "cadeia"],
    "Agents": ["agente", "agents", "autonom", "copiloto"],
    "Governance/Risk": ["governanca", "guardrail", "risco", "compliance", "regulat"],
    "People/Talent": ["equipe", "talento", "ansiedade", "treinamento", "cultura"],
    "Growth/Commercial": ["cliente", "conversao", "comercial", "crescimento", "leads"],
    "Strategy": ["estrategi", "caso de uso", "priorizacao"],
}


def extract_semantic_tags(open_text: str) -> set[str]:
    n = _norm(open_text)
    tags = set()
    for tag, kws in _CHALLENGE_KEYWORDS.items():
        if any(kw in n for kw in kws):
            tags.add(tag)
    return tags


@dataclass
class Participant:
    participant_id: str
    function: str
    industry: str
    interests: set = field(default_factory=set)
    ai_maturity: int = 0          # ordinal 0..3
    axis_workflow: int = 0        # -2..+2
    axis_autonomy: int = 0        # -2..+2
    axis_speed_governance: int = 0  # -2..+2
    axis_missing: set = field(default_factory=set)  # quais eixos vieram nulos
    open_challenge: str = ""
    semantic_tags: set = field(default_factory=set)
    next_activities: list = field(default_factory=list)  # ordem = preferencia
    company: str | None = None
    networking_opt_in: bool = True

    @property
    def primary_next_activity(self) -> str:
        return self.next_activities[0] if self.next_activities else "Networking Lunch"

    @property
    def all_tags(self) -> set:
        return self.interests | self.semantic_tags


def load_participants(csv_path: str) -> list[Participant]:
    participants = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row["ID"].strip()
            function = map_keyword(row["Função/Área"], _FUNCTION_KEYWORDS, FUNCTIONS)
            industry = map_keyword(row["Setor"], _INDUSTRY_KEYWORDS, INDUSTRIES)
            interests = {i.strip() for i in row["Interesses (2 a 3)"].split(";") if i.strip()}
            maturity_raw = row["Estágio da Org."].strip()
            ai_maturity = MATURITY_ORDER.get(maturity_raw, 1)
            axis_w, miss_w = map_axis(row["T1"])
            axis_a, miss_a = map_axis(row["T2"])
            axis_g, miss_g = map_axis(row["T3"])
            missing = set()
            if miss_w:
                missing.add("axis_workflow")
            if miss_a:
                missing.add("axis_autonomy")
            if miss_g:
                missing.add("axis_speed_governance")
            open_challenge = row["Desafio Atual (Aberto)"].strip().strip('"')
            semantic_tags = extract_semantic_tags(open_challenge)
            next_activities = map_next_activity(row["Interesse em Palestras (Múltipla Escolha)"])
            opt_in = _norm(row["Opt-in Networking?"]) == "sim"

            participants.append(Participant(
                participant_id=pid,
                function=function,
                industry=industry,
                interests=interests,
                ai_maturity=ai_maturity,
                axis_workflow=axis_w,
                axis_autonomy=axis_a,
                axis_speed_governance=axis_g,
                axis_missing=missing,
                open_challenge=open_challenge,
                semantic_tags=semantic_tags,
                next_activities=next_activities,
                company=None,  # nao presente na planilha de teste
                networking_opt_in=opt_in,
            ))
    return participants
