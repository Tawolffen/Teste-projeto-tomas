# -*- coding: utf-8 -*-
"""
rationale.py
Gera rationale executivo curto e conversation starter por POD (nao por
pessoa -- secao 14.3: "o rationale e o prompt precisam ser compartilhados no
nivel do pod; nao hiperpersonalizar").

Isto e o caminho de TEMPLATE citado na secao 10 (FALLBACK - LLM indisponivel):
"Rationale usa templates deterministas. Conversation starter vem de template
por theme/pod." Nenhuma chamada de IA e feita aqui. Se/quando um LLM_ENABLED
existir, este modulo e o ponto natural para trocar por um AI Adapter mantendo
o mesmo contrato de saida (rationale: str, starter: str).
"""
from __future__ import annotations
from collections import Counter

from normalize import Participant
from scoring import pod_average_score
from zones import Zone

STARTER_TEMPLATES = {
    "A": "Onde voces estao hoje: otimizando o que ja existe ou redesenhando do zero — e por que?",
    "B": "Onde a aprovacao humana deveria continuar obrigatoria, mesmo com agentes mais capazes?",
    "C": "Qual parte do time ou do fluxo de trabalho vai mudar primeiro com IA — e quem sente isso primeiro?",
}

TAG_LABEL = {
    "Scaling/Value": "escalar valor a partir de pilotos",
    "Workflow Redesign": "redesenhar processos do zero",
    "Data/Tech": "arquitetura de dados e modelos",
    "Operations": "operacoes e cadeia de valor",
    "Agents": "agentes autonomos",
    "Governance/Risk": "governanca e risco",
    "People/Talent": "pessoas e talento",
    "Growth/Commercial": "crescimento comercial",
    "Strategy": "priorizacao estrategica",
}

ACTIVITY_LABEL = {
    "Future of Operations": "O Futuro das Operacoes",
    "Reinvention of Commerce": "A Reinvencao do Comercio",
    "Future of Financial Services": "Como agentes de IA estao redefinindo os servicos financeiros",
    "Networking Lunch": "o Networking Lunch",
}


def _top_tags(members: list[Participant], n=2) -> list[str]:
    c = Counter()
    for p in members:
        c.update(p.all_tags)
    return [t for t, _ in c.most_common(n)]


def _dominant_next_activity(members: list[Participant]) -> tuple[str, float]:
    c = Counter(p.primary_next_activity for p in members)
    top, count = c.most_common(1)[0]
    return top, count / len(members)


def _function_spread(members: list[Participant]) -> int:
    return len({p.function for p in members})


def build_pod_rationale(zone: Zone, members: list[Participant]) -> dict:
    """Retorna {'rationale': str, 'starter': str}. Pod deve ter >=2 membros."""
    if len(members) < 2:
        return {"rationale": "", "starter": ""}

    scores = pod_average_score(members)
    tags = _top_tags(members, n=2)
    tag_phrase = " e ".join(TAG_LABEL.get(t, t) for t in tags) if tags else "o momento atual de IA"
    n_functions = _function_spread(members)
    activity, share = _dominant_next_activity(members)
    activity_label = ACTIVITY_LABEL.get(activity, activity)

    # Rationale: common ground (tags) + complementarity (funcoes) + continuity (next activity)
    common_ground_txt = f"Este grupo compartilha interesse em {tag_phrase}."
    if scores["complementarity"] >= 0.5 and n_functions >= 3:
        complementarity_txt = (f" Ao mesmo tempo, reune {n_functions} funcoes diferentes, "
                                f"trazendo angulos distintos sobre o mesmo tema.")
    elif n_functions >= 2:
        complementarity_txt = " Vem de areas diferentes o suficiente para gerar perspectivas complementares."
    else:
        complementarity_txt = ""

    if share >= 0.7:
        continuity_txt = (f" A maior parte do pod pretende seguir para {activity_label} depois — "
                           f"a conversa pode continuar la.")
    elif share >= 0.4:
        continuity_txt = f" Boa parte do grupo tambem vai para {activity_label} em seguida."
    else:
        continuity_txt = ""

    rationale = (common_ground_txt + complementarity_txt + continuity_txt).strip()

    starter = STARTER_TEMPLATES.get(zone.code, "Qual e o proximo passo de IA que voces mais discutem hoje?")
    if tags:
        starter = f"Comecem por aqui: {tag_phrase}. {starter}"

    return {"rationale": rationale, "starter": starter}
