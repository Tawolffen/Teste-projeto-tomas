# -*- coding: utf-8 -*-
"""
pods.py
Formacao de pods dinamicos dentro de cada macrozona (secao 6) e refinamento
local (secao 9, passos 1-7 do "Fallback heuristico" -- aqui usado como etapa
regular de composicao fina, ver nota em optimizer.py).

Passos implementados:
 1. separar por next_activity dentro da zona
 2. estratificar grupos pequenos demais (merge com maior grupo da zona)
 3. interleave por funcao/eixos (round-robin) para semear complementaridade
 4. formar buckets respeitando target/max capacity
 5. refinamento local: swaps entre pods da MESMA zona que aumentem o
    ConversationValue medio agregado dos dois pods envolvidos
"""
from __future__ import annotations
import random
from collections import defaultdict

from normalize import Participant
from scoring import pod_average_score, conversation_value

TARGET_MIN = 8
TARGET_MAX = 15
MIN_STRATUM = 5          # abaixo disso, o grupo de next_activity e mesclado
SWAP_ITERATIONS = 400


def _stratify_by_next_activity(members: list[Participant]) -> list[list[Participant]]:
    groups = defaultdict(list)
    for p in members:
        groups[p.primary_next_activity].append(p)
    # ordenar do maior para o menor grupo
    ordered = sorted(groups.values(), key=len, reverse=True)
    # mesclar grupos pequenos demais no maior grupo disponivel (evita pods de 1-2 pessoas
    # so por causa de session continuity -- que e soft preference, secao 3)
    if len(ordered) <= 1:
        return ordered
    big, *rest = ordered
    merged_small = []
    kept = [big]
    for g in rest:
        if len(g) < MIN_STRATUM:
            merged_small.extend(g)
        else:
            kept.append(g)
    if merged_small:
        kept.append(merged_small)
    return kept


def _interleave_by_function(members: list[Participant]) -> list[Participant]:
    """Round-robin por funcao para nao concentrar a mesma funcao no inicio do bucket."""
    buckets = defaultdict(list)
    for p in members:
        buckets[p.function].append(p)
    for b in buckets.values():
        random.shuffle(b)
    order = []
    keys = list(buckets.keys())
    while any(buckets[k] for k in keys):
        for k in keys:
            if buckets[k]:
                order.append(buckets[k].pop())
    return order


def _chunk_into_pods(ordered: list[Participant]) -> list[list[Participant]]:
    n = len(ordered)
    if n == 0:
        return []
    if n <= TARGET_MAX:
        return [ordered]  # zona/estrato pequeno: um unico pod (secao 6)
    n_pods = max(1, round(n / ((TARGET_MIN + TARGET_MAX) / 2)))
    base = n // n_pods
    rem = n % n_pods
    pods, i = [], 0
    for k in range(n_pods):
        size = base + (1 if k < rem else 0)
        pods.append(ordered[i:i + size])
        i += size
    return pods


def _local_swap_refine(pods: list[list[Participant]], iterations: int = SWAP_ITERATIONS):
    """Hill-climbing: troca dois membros entre pods da mesma zona se a soma
    dos scores medios dos dois pods melhorar. Reduz concentracao de mesma
    empresa/funcao e melhora complementaridade (secao 9, passo 5)."""
    if len(pods) < 2:
        return pods
    for _ in range(iterations):
        i, j = random.sample(range(len(pods)), 2)
        if not pods[i] or not pods[j]:
            continue
        a_idx = random.randrange(len(pods[i]))
        b_idx = random.randrange(len(pods[j]))
        before = (pod_average_score(pods[i])["total"] + pod_average_score(pods[j])["total"])
        pods[i][a_idx], pods[j][b_idx] = pods[j][b_idx], pods[i][a_idx]
        after = (pod_average_score(pods[i])["total"] + pod_average_score(pods[j])["total"])
        if after < before:
            # reverte (nao melhorou)
            pods[i][a_idx], pods[j][b_idx] = pods[j][b_idx], pods[i][a_idx]
    return pods


def form_pods_for_zone(zone_code: str, members: list[Participant], seed: int = 42) -> list[list[Participant]]:
    if not members:
        return []
    random.seed(seed)
    strata = _stratify_by_next_activity(members)
    all_pods: list[list[Participant]] = []
    for stratum in strata:
        interleaved = _interleave_by_function(stratum)
        all_pods.extend(_chunk_into_pods(interleaved))
    # merge de pods residuais muito pequenos (< TARGET_MIN) com o pod mais compativel
    all_pods = [p for p in all_pods if p]
    small = [p for p in all_pods if len(p) < TARGET_MIN and len(all_pods) > 1]
    for s in small:
        if s not in all_pods:
            continue
        all_pods.remove(s)
        if not all_pods:
            all_pods.append(s)
            continue
        target = max(all_pods, key=lambda pod: len(pod) < TARGET_MAX)
        candidates = [pod for pod in all_pods if len(pod) + len(s) <= TARGET_MAX + 2]
        target = candidates[0] if candidates else min(all_pods, key=len)
        target.extend(s)
    all_pods = _local_swap_refine(all_pods)
    return all_pods
