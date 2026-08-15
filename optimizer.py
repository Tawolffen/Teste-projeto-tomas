# -*- coding: utf-8 -*-
"""
optimizer.py
Etapa 1 da alocacao global (secao 9): atribuir cada participante opt-in a uma
macrozona (A/B/C) maximizando afinidade tematica agregada, respeitando que
zonas nao ficam vazias/desbalanceadas sem necessidade -- sem forcar simetria
25/25/25 (regra explicita da secao 3/9).

Por que dividir em duas etapas (zona -> pod) em vez de um unico CP-SAT
quadratico sobre pares de pessoas:
o ConversationValue da secao 7 e uma funcao PAIRWISE (depende de pares dentro
do mesmo pod). Resolver a atribuicao ótima de pods diretamente como problema
quadratico de particionamento (quem fica com quem) é NP-hard e, para N~200-300
e pods de 8-15, o numero de variaveis de produto (x_i,k * x_j,k) explode e nao
termina em tempo de demo. A propria secao 9 do dossie autoriza esse tipo de
solucao pragmatica ("Feasible > optimal"): usamos CP-SAT para a parte que É
genuinamente um problema de atribuicao linear bem resolvido por um solver
(pessoa -> zona, maximizando common ground agregado com balanceamento), e
heuristica com refinamento local (pods.py) para a composicao fina dentro de
cada zona -- exatamente o "fallback heuristico" descrito na secao 9, promovido
aqui a etapa regular do pipeline por ser a escolha de engenharia mais robusta
dentro do prazo, e nao apenas um caminho de degradacao.
"""
from __future__ import annotations
from ortools.sat.python import cp_model

from normalize import Participant
from scoring import theme_affinity
from zones import GUIDED_ZONES, ZONE_BY_CODE

SCALE = 1000  # CP-SAT trabalha com inteiros; escalamos os floats de afinidade
BALANCE_WEIGHT = 0.15  # peso do termo de balanceamento suave (nao-forcado)
TIMEOUT_SECONDS = 20


def assign_zones(participants: list[Participant]) -> tuple[dict[str, str], str, float]:
    """
    Retorna (zone_by_participant_id, solver_status, runtime_ms).
    Participantes com networking_opt_in=False vao direto para 'D' (Open
    Networking) e nao entram no modelo.
    """
    guided = [p for p in participants if p.networking_opt_in]
    opted_out = [p for p in participants if not p.networking_opt_in]

    zone_by_pid: dict[str, str] = {p.participant_id: "D" for p in opted_out}

    if not guided:
        return zone_by_pid, "NO_GUIDED_PARTICIPANTS", 0.0

    zones = GUIDED_ZONES  # A, B, C
    model = cp_model.CpModel()

    x = {}
    for p in guided:
        for z in zones:
            x[p.participant_id, z.code] = model.NewBoolVar(f"x_{p.participant_id}_{z.code}")

    # cada participante guiado recebe exatamente uma zona
    for p in guided:
        model.Add(sum(x[p.participant_id, z.code] for z in zones) == 1)

    # tamanho de cada zona + termo de balanceamento suave (nao e hard constraint)
    n = len(guided)
    target = n // len(zones)
    dev_vars = []
    for z in zones:
        size_var = model.NewIntVar(0, n, f"size_{z.code}")
        model.Add(size_var == sum(x[p.participant_id, z.code] for p in guided))
        dev = model.NewIntVar(0, n, f"dev_{z.code}")
        model.AddAbsEquality(dev, size_var - target)
        dev_vars.append(dev)

    # objetivo: maximizar afinidade tematica agregada - penalidade leve de desbalanceamento
    affinity_terms = []
    for p in guided:
        for z in zones:
            score = int(round(theme_affinity(p, z) * SCALE))
            affinity_terms.append(score * x[p.participant_id, z.code])

    model.Maximize(sum(affinity_terms) - int(BALANCE_WEIGHT * SCALE) * sum(dev_vars))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIMEOUT_SECONDS
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    runtime_ms = solver.WallTime() * 1000

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for p in guided:
            for z in zones:
                if solver.Value(x[p.participant_id, z.code]):
                    zone_by_pid[p.participant_id] = z.code
                    break
    else:
        # fallback puro: cada um vai para a zona de maior afinidade individual
        for p in guided:
            best = max(zones, key=lambda z: theme_affinity(p, z))
            zone_by_pid[p.participant_id] = best.code
        status_name = "FALLBACK_" + status_name

    return zone_by_pid, status_name, runtime_ms
