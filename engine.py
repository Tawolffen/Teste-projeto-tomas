# -*- coding: utf-8 -*-
"""
engine.py
Ponto de entrada do motor de matching. Roda o pipeline completo descrito no
dossie (secao 1, "Fluxo canonico"; secao 9, "Otimizacao global"):

  CSV bruto -> normalize -> assign_zones (CP-SAT) -> form_pods_for_zone
  (heuristica + refinamento local) -> scoring/explainability -> outputs

Uso:
    python engine.py caminho/para/tabela.csv --outdir /mnt/user-data/outputs
"""
from __future__ import annotations
import argparse
import csv
import json
import time
from collections import Counter

from normalize import load_participants, Participant
from optimizer import assign_zones
from pods import form_pods_for_zone, TARGET_MIN, TARGET_MAX
from scoring import pod_average_score
from zones import ZONE_BY_CODE, GUIDED_ZONES
from rationale import build_pod_rationale


def run_pipeline(csv_path: str):
    participants = load_participants(csv_path)

    t0 = time.time()
    zone_by_pid, solver_status, solver_runtime_ms = assign_zones(participants)
    zone_assign_ms = (time.time() - t0) * 1000

    by_zone: dict[str, list[Participant]] = {z.code: [] for z in ZONE_BY_CODE.values()}
    for p in participants:
        by_zone[zone_by_pid[p.participant_id]].append(p)

    pods_by_zone: dict[str, list[list[Participant]]] = {}
    for z in GUIDED_ZONES:
        pods_by_zone[z.code] = form_pods_for_zone(z.code, by_zone[z.code])
    # Open Networking (D) nao forma pods -- e um espaco unico e aberto (secao 6 e 14.4)
    pods_by_zone["D"] = [by_zone["D"]] if by_zone["D"] else []

    meta = {
        "solver_status": solver_status,
        "solver_runtime_ms": round(solver_runtime_ms, 1),
        "zone_assignment_wall_ms": round(zone_assign_ms, 1),
        "algorithm_mode": "optimizer" if "FALLBACK" not in solver_status else "fallback",
        "n_total": len(participants),
        "n_opt_in": sum(1 for p in participants if p.networking_opt_in),
        "n_opt_out": sum(1 for p in participants if not p.networking_opt_in),
    }
    return participants, by_zone, pods_by_zone, meta


def build_assignments_table(pods_by_zone) -> list[dict]:
    rows = []
    for zone_code, pods in pods_by_zone.items():
        zone = ZONE_BY_CODE[zone_code]
        for pod_idx, members in enumerate(pods, start=1):
            pod_id = f"{zone_code}{pod_idx if len(pods) > 1 else ''}" if zone_code != "D" else "OPEN"
            scores = pod_average_score(members) if len(members) > 1 else None
            rat = build_pod_rationale(zone, members) if zone_code != "D" and len(members) > 1 else {"rationale": "", "starter": ""}
            for p in members:
                rows.append({
                    "participant_id": p.participant_id,
                    "zone": zone_code,
                    "zone_title": zone.title,
                    "pod_id": pod_id,
                    "pod_size": len(members),
                    "function": p.function,
                    "industry": p.industry,
                    "ai_maturity": p.ai_maturity,
                    "primary_next_activity": p.primary_next_activity,
                    "networking_opt_in": p.networking_opt_in,
                    "pod_common_ground": round(scores["common_ground"], 3) if scores else "",
                    "pod_complementarity": round(scores["complementarity"], 3) if scores else "",
                    "pod_useful_diversity": round(scores["useful_diversity"], 3) if scores else "",
                    "pod_session_continuity": round(scores["session_continuity"], 3) if scores else "",
                    "pod_friction": round(scores["friction"], 3) if scores else "",
                    "pod_total_score": round(scores["total"], 3) if scores else "",
                    "pod_rationale": rat["rationale"],
                    "pod_starter": rat["starter"],
                })
    return rows


def build_pods_index(pods_by_zone) -> dict:
    """Estrutura consultavel por pod_id: membros, scores, rationale, starter.
    Usada pelo query.py e persistida em pods_index.json."""
    index = {}
    for zone_code, pods in pods_by_zone.items():
        zone = ZONE_BY_CODE[zone_code]
        for pod_idx, members in enumerate(pods, start=1):
            if zone_code == "D":
                pod_id = "OPEN"
            else:
                pod_id = f"{zone_code}{pod_idx if len(pods) > 1 else ''}"
            scores = pod_average_score(members) if len(members) > 1 else None
            rat = (build_pod_rationale(zone, members)
                   if zone_code != "D" and len(members) > 1 else {"rationale": "", "starter": ""})
            index[pod_id] = {
                "zone": zone_code,
                "zone_title": zone.title,
                "zone_tension": zone.tension,
                "size": len(members),
                "participant_ids": [p.participant_id for p in members],
                "scores": scores,
                "rationale": rat["rationale"],
                "starter": rat["starter"],
            }
    return index


def write_assignments_csv(rows: list[dict], path: str):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_explainability_report(pods_by_zone, meta) -> str:
    lines = []
    lines.append("# Rewire the Room — Relatorio de Explainability do Matching\n")
    lines.append(f"- Status do solver (Etapa 1, zonas): **{meta['solver_status']}**")
    lines.append(f"- Runtime do solver: {meta['solver_runtime_ms']} ms")
    lines.append(f"- Modo do algoritmo: **{meta['algorithm_mode']}**")
    lines.append(f"- Total de participantes: {meta['n_total']} "
                 f"(opt-in: {meta['n_opt_in']}, opt-out/Open Networking: {meta['n_opt_out']})\n")

    for zone_code, pods in pods_by_zone.items():
        zone = ZONE_BY_CODE[zone_code]
        if zone_code == "D":
            lines.append(f"## Zona D — {zone.title}")
            n = len(pods[0]) if pods else 0
            lines.append(f"Participantes em Open Networking: {n} (fluxo positivo, sem pods atribuidos).\n")
            continue

        lines.append(f"## Zona {zone_code} — {zone.title}")
        lines.append(f"*{zone.tension}*\n")
        if not pods:
            lines.append("_Nenhum participante alocado nesta zona._\n")
            continue

        for idx, members in enumerate(pods, start=1):
            pod_label = f"{zone_code}{idx if len(pods) > 1 else ''}"
            scores = pod_average_score(members) if len(members) > 1 else None
            fn_counts = Counter(p.function for p in members)
            ind_counts = Counter(p.industry for p in members)
            act_counts = Counter(p.primary_next_activity for p in members)
            maturity_counts = Counter(p.ai_maturity for p in members)
            top_tags = Counter()
            for p in members:
                top_tags.update(p.all_tags)

            lines.append(f"### Pod {pod_label}  (n={len(members)})")
            if scores:
                lines.append(
                    f"- ConversationValue medio: **{scores['total']:.2f}**  "
                    f"(common_ground={scores['common_ground']:.2f}, "
                    f"complementarity={scores['complementarity']:.2f}, "
                    f"useful_diversity={scores['useful_diversity']:.2f}, "
                    f"session_continuity={scores['session_continuity']:.2f}, "
                    f"friction={scores['friction']:.2f})"
                )
            lines.append(f"- Funcoes: {dict(fn_counts)}")
            lines.append(f"- Setores: {dict(ind_counts)}")
            lines.append(f"- Maturidade IA (0=Exploring..3=Embedded): {dict(maturity_counts)}")
            lines.append(f"- Proxima atividade pretendida: {dict(act_counts)}")
            top5 = [t for t, _ in top_tags.most_common(5)]
            lines.append(f"- Temas/tags mais comuns no pod: {top5}")
            if len(members) > 1:
                rat = build_pod_rationale(zone, members)
                lines.append(f"- **Rationale:** {rat['rationale']}")
                lines.append(f"- **Conversation starter:** {rat['starter']}")
            lines.append(f"- Participantes: {[p.participant_id for p in members]}\n")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Rewire the Room - motor de matching")
    ap.add_argument("csv_path")
    ap.add_argument("--outdir", default=".")
    args = ap.parse_args()

    participants, by_zone, pods_by_zone, meta = run_pipeline(args.csv_path)

    rows = build_assignments_table(pods_by_zone)
    write_assignments_csv(rows, f"{args.outdir}/assignments.csv")

    report = build_explainability_report(pods_by_zone, meta)
    with open(f"{args.outdir}/explainability_report.md", "w", encoding="utf-8") as f:
        f.write(report)

    with open(f"{args.outdir}/run_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    pods_index = build_pods_index(pods_by_zone)
    with open(f"{args.outdir}/pods_index.json", "w", encoding="utf-8") as f:
        json.dump(pods_index, f, ensure_ascii=False, indent=2)

    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"\nZonas: " + ", ".join(f"{z}={len(by_zone[z])}" for z in by_zone))
    print(f"Pods por zona: " + ", ".join(f"{z}={len(pods_by_zone[z])}" for z in pods_by_zone))


if __name__ == "__main__":
    main()
