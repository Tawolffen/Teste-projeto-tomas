# -*- coding: utf-8 -*-
"""
scoring.py
Implementa a funcao objetivo conceitual da secao 7:

    ConversationValue = alpha*CommonGround + beta*Complementarity
                       + gamma*UsefulDiversity + eta*SessionContinuity
                       - delta*Friction

Os pesos vivem em um unico lugar (MATCHING_WEIGHTS, secao 8.6), auditavel e
calibravel sem tocar no algoritmo.
"""
from __future__ import annotations
from normalize import Participant
from zones import Zone

# ---------------------------------------------------------------------------
# Pesos configuraveis (secao 8.6) — unico ponto de calibracao
# ---------------------------------------------------------------------------
MATCHING_WEIGHTS = {
    "common_ground": 1.0,
    "complementarity": 0.8,
    "useful_diversity": 0.5,
    "session_continuity": 0.9,
    "same_company_penalty": 0.6,
    "extreme_distance_penalty": 0.7,
}

AXES = ["axis_workflow", "axis_autonomy", "axis_speed_governance"]


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ---------------------------------------------------------------------------
# Afinidade participante <-> zona (usada na Etapa 1 / atribuicao de zona)
# ---------------------------------------------------------------------------
def theme_affinity(p: Participant, zone: Zone) -> float:
    """Common ground do participante com a tensao tematica da zona (secao 8.2)."""
    if not zone.theme_tags:
        return 0.0
    return jaccard(p.all_tags, zone.theme_tags)


# ---------------------------------------------------------------------------
# Componentes pairwise (secao 8.2 a 8.5)
# ---------------------------------------------------------------------------
def common_ground(p: Participant, q: Participant) -> float:
    interest_overlap = jaccard(p.interests, q.interests)
    challenge_align = 1.0 if (p.semantic_tags & q.semantic_tags) else 0.0
    maturity_dist = abs(p.ai_maturity - q.ai_maturity)
    maturity_compat = max(0.0, 1.0 - maturity_dist / 3.0)
    semantic_affinity = jaccard(p.semantic_tags, q.semantic_tags)
    return (0.4 * interest_overlap + 0.2 * challenge_align
            + 0.25 * maturity_compat + 0.15 * semantic_affinity)


def complementarity(p: Participant, q: Participant) -> float:
    score = 0.0
    has_common = jaccard(p.all_tags, q.all_tags) > 0
    if p.function != q.function and has_common:
        score += 0.35
    if p.industry != q.industry:
        score += 0.20
    # eixos: diferenca MODERADA e valiosa; diferenca extrema (4) sem common
    # ground vira friccao (tratada em friction()), nao complementaridade.
    for axis in AXES:
        d = abs(getattr(p, axis) - getattr(q, axis))
        if 1 <= d <= 2:
            score += 0.15 / len(AXES) * 3  # bônus moderado por eixo com diferenca util
    return min(score, 1.0)


def useful_diversity(p: Participant, q: Participant) -> float:
    variety = 0
    total = 4
    if p.function != q.function:
        variety += 1
    if p.industry != q.industry:
        variety += 1
    if p.ai_maturity != q.ai_maturity:
        variety += 1
    if any(abs(getattr(p, a) - getattr(q, a)) >= 1 for a in AXES):
        variety += 1
    raw = variety / total
    # deve existir *algum* terreno comum; sem isso, diversidade nao e "util"
    if jaccard(p.all_tags, q.all_tags) == 0 and not (p.semantic_tags & q.semantic_tags):
        raw *= 0.5
    return raw


def session_continuity(p: Participant, q: Participant) -> float:
    if p.primary_next_activity == q.primary_next_activity:
        return 1.0
    if p.primary_next_activity in q.next_activities or q.primary_next_activity in p.next_activities:
        return 0.5
    return 0.0


def friction(p: Participant, q: Participant) -> float:
    f = 0.0
    if p.company and q.company and p.company == q.company:
        f += MATCHING_WEIGHTS["same_company_penalty"]
    extreme_axis = any(abs(getattr(p, a) - getattr(q, a)) >= 3 for a in AXES)
    no_common = jaccard(p.all_tags, q.all_tags) == 0 and not (p.semantic_tags & q.semantic_tags)
    if extreme_axis and no_common:
        f += MATCHING_WEIGHTS["extreme_distance_penalty"]
    return f


def conversation_value(p: Participant, q: Participant, w=MATCHING_WEIGHTS) -> float:
    return (w["common_ground"] * common_ground(p, q)
            + w["complementarity"] * complementarity(p, q)
            + w["useful_diversity"] * useful_diversity(p, q)
            + w["session_continuity"] * session_continuity(p, q)
            - friction(p, q))


# ---------------------------------------------------------------------------
# Agregacao a nivel de pod (para o optimizer/heuristica e para explainability)
# ---------------------------------------------------------------------------
def pod_average_score(members: list[Participant]) -> dict:
    n = len(members)
    if n < 2:
        return {"common_ground": 0, "complementarity": 0, "useful_diversity": 0,
                "session_continuity": 0, "friction": 0, "total": 0}
    pairs = [(members[i], members[j]) for i in range(n) for j in range(i + 1, n)]
    agg = {"common_ground": 0.0, "complementarity": 0.0, "useful_diversity": 0.0,
           "session_continuity": 0.0, "friction": 0.0, "total": 0.0}
    for p, q in pairs:
        agg["common_ground"] += common_ground(p, q)
        agg["complementarity"] += complementarity(p, q)
        agg["useful_diversity"] += useful_diversity(p, q)
        agg["session_continuity"] += session_continuity(p, q)
        agg["friction"] += friction(p, q)
        agg["total"] += conversation_value(p, q)
    for k in agg:
        agg[k] /= len(pairs)
    return agg
