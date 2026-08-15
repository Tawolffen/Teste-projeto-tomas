# -*- coding: utf-8 -*-
"""
query.py
Consulta rapida em cima do pods_index.json gerado pelo engine.py.

Uso:
    python query.py out/pods_index.json --pod A1
    python query.py out/pods_index.json --participant 122
    python query.py out/pods_index.json --list
"""
from __future__ import annotations
import argparse
import json


def load_index(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def print_pod(pod_id: str, pod: dict):
    print(f"\n=== POD {pod_id}  ({pod['zone']} — {pod['zone_title']}) ===")
    print(f"Tensao: {pod['zone_tension']}")
    print(f"Tamanho: {pod['size']}")
    if pod["scores"]:
        s = pod["scores"]
        print(f"ConversationValue medio: {s['total']:.2f}  "
              f"(common_ground={s['common_ground']:.2f}, complementarity={s['complementarity']:.2f}, "
              f"useful_diversity={s['useful_diversity']:.2f}, session_continuity={s['session_continuity']:.2f}, "
              f"friction={s['friction']:.2f})")
    print(f"\nRationale:\n  {pod['rationale']}")
    print(f"\nConversation starter:\n  {pod['starter']}")
    print(f"\nParticipantes ({pod['size']}): {', '.join(pod['participant_ids'])}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("index_path", help="caminho para pods_index.json")
    ap.add_argument("--pod", help="ID do pod, ex: A1, B3, OPEN")
    ap.add_argument("--participant", help="ID do participante (busca o pod dele)")
    ap.add_argument("--list", action="store_true", help="lista todos os pods e tamanhos")
    args = ap.parse_args()

    index = load_index(args.index_path)

    if args.list:
        for pod_id, pod in index.items():
            print(f"{pod_id:6s} zona={pod['zone']:2s} n={pod['size']:3d}  {pod['zone_title']}")
        return

    if args.pod:
        pod = index.get(args.pod)
        if not pod:
            print(f"Pod '{args.pod}' nao encontrado. Use --list para ver os IDs disponiveis.")
            return
        print_pod(args.pod, pod)
        return

    if args.participant:
        for pod_id, pod in index.items():
            if args.participant in pod["participant_ids"]:
                print_pod(pod_id, pod)
                return
        print(f"Participante '{args.participant}' nao encontrado em nenhum pod (pode estar em Open Networking sem pod, ou opt-out).")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
