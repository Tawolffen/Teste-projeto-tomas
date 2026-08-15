# -*- coding: utf-8 -*-
"""
zones.py
Macrozonas semanticas fixas do produto (secao 6). D e reservada para
Open Networking (opt-out); nunca recebe alocacao guiada.
"""
from dataclasses import dataclass


@dataclass
class Zone:
    code: str
    title: str
    tension: str
    # tags de interesse/desafio que sinalizam afinidade tematica com a zona
    theme_tags: set
    # eixo de tensao mais relevante para esta zona (usado na explainability)
    axis_focus: str | None


ZONES = [
    Zone("A", "Rewire for Value",
         "Como sair de experimentos e gerar valor? Otimizar o fluxo atual ou redesenha-lo?",
         theme_tags={"Scaling/Value", "Workflow Redesign", "Growth/Commercial"},
         axis_focus="axis_workflow"),
    Zone("B", "Trust x Autonomy",
         "Quanto controle entregar a agentes e onde governanca/supervisao precisam permanecer fortes?",
         theme_tags={"Agents", "Governance/Risk", "Data/Tech"},
         axis_focus="axis_autonomy"),
    Zone("C", "The New Operating Model",
         "Como IA muda papeis, equipes, workflows e formas de operar?",
         theme_tags={"Operations", "People/Talent", "Strategy"},
         axis_focus="axis_speed_governance"),
    Zone("D", "Open Networking",
         "Espaco espontaneo para quem nao quer recomendacao ou prefere networking livre.",
         theme_tags=set(),
         axis_focus=None),
]

ZONE_BY_CODE = {z.code: z for z in ZONES}
GUIDED_ZONES = [z for z in ZONES if z.code != "D"]
