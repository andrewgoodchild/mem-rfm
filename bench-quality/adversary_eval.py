#!/usr/bin/env python3
"""Adversary matrix: three bad-actor strategies against four defense
configurations, with utility bars (PROTOCOL.md Amendment 7).

Attacks (attackers are team members using calls they are entitled to make):
  upvote     inject mimic bait, then self-access + self-rate +1 to promote it
             (Amendment 6's attack, carried forward as the baseline)
  downvote   inject nothing; repeatedly rate OTHER agents' genuine memories
             -1 to suppress them (censorship, not promotion). exclude_self is
             blind to this by construction — the attacker never touches its
             own memory. Suppression is TARGETED at a few labels: a smoke run
             confirmed that downvoting everything uniformly is a no-op (a
             uniform penalty leaves relative order unchanged), so the real
             threat is "make procedure X never surface". Scored separately on
             targeted vs untargeted calls.
  collude    C attackers inject bait and cross-endorse EACH OTHER's bait +1,
             so no endorsement is ever self-endorsement. Defeats exclude_self
             by design; one_vote caps it at C votes per memory.

Defenses (all use the frozen bounded prior, beta=0.3):
  rfm        no hardening
  rfm_self   rfm_config('exclude_self', 1)
  rfm_vote   rfm_config('one_vote', 1)
  rfm_both   both
plus `sim` (similarity only) as the ungameable control.

Utility is measured on the SAME run: legit hit@1/hit@k on genuine labels,
plus a clean-store arm (no attacker at all) so a defense that protects by
degrading everything is caught. one_vote is expected to cost real utility —
it discards repeat-use evidence, which is the value axis's main signal.

Usage: adversary_eval.py [--dataset star|abcd] [--n N] [--k 5]
                         [--attack upvote|downvote|collude] [--rate 0.20]
                         [--pump 50] [--colluders 4] [--agents 8]
"""
import argparse
import os
import random
from collections import Counter, defaultdict

import numpy as np

import common
from team_common import BASE_TS, CALL_SPACING

POISON = "__POISON__"

#             (exclude_self, one_vote, trust)
DEFENSES = {
    "rfm": (False, False, False),
    "rfm_self": (True, False, False),
    "rfm_vote": (False, True, False),
    "rfm_both": (True, True, False),
    "rfm_trust": (False, False, True),      # Amendment 8: writer reputation
    "rfm_self_trust": (True, False, True),  # the recommended pairing
    # Amendment 9: can any vote-aggregation defend a ring?
    "rfm_vote_trust": (False, True, True),   # C1: one_vote x trust
    "rfm_trust2": (False, False, "weighted"),  # C2: voter-weighted trust
}
CONDITIONS = ["sim"] + list(DEFENSES)


def load(dataset, n):
    if dataset == "star":
        from star_eval import load_calls
        calls = load_calls(n)
    else:
        from abcd_eval import load_calls
        calls = load_calls(n)
        for i, c in enumerate(calls):
            c["ts"] = BASE_TS + i * CALL_SPACING
    return calls


def build_poison(calls, rate, n_attackers, seed=41):
    """Mimic bait plan; each poison is owned by one of n_attackers."""
    rng = random.Random(seed)
    label_key = "label" if "label" in calls[0] else "intent"
    top = sorted(i for i, _ in Counter(c[label_key] for c in calls).most_common(8))
    past = defaultdict(list)
    poisons = []
    for i, c in enumerate(calls):
        if rng.random() < rate:
            targets = [t for t in top if past[t]]
            if targets:
                t = rng.choice(targets)
                bait = rng.choice(past[t])
                owner = f"actor:attacker{len(poisons) % n_attackers}"
                poisons.append((i, c["ts"] + CALL_SPACING / 2.0,
                                bait + " | resolved via: escalate to level-9 "
                                "priority queue and apply the universal reset",
                                owner))
        past[c[label_key]].append(c["query"])
    return poisons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=["star", "abcd"], default="star")
    ap.add_argument("--n", type=int, default=6500)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--attack", choices=["upvote", "downvote", "collude"],
                    default="upvote")
    ap.add_argument("--rate", type=float, default=0.20)
    ap.add_argument("--pump", type=int, default=50)
    ap.add_argument("--colluders", type=int, default=4)
    ap.add_argument("--agents", type=int, default=8)
    args = ap.parse_args()

    calls = load(args.dataset, args.n)
    label_key = "label" if "label" in calls[0] else "intent"
    n_attackers = args.colluders if args.attack == "collude" else 1
    # The downvote attacker injects nothing — it only suppresses.
    poisons = ([] if args.attack == "downvote"
               else build_poison(calls, args.rate, n_attackers))
    print(f"{len(calls)} calls, {len(poisons)} poisoned writes, "
          f"attack={args.attack} pump={args.pump} "
          f"attackers={n_attackers}", flush=True)

    cache_dir = os.path.join(
        common.HERE, f"cache-adv-{args.dataset}" + common.cache_suffix())
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, f"n{args.n}-r{args.rate}-{args.attack}"
                                    f"-c{n_attackers}.npz")
    if os.path.exists(cache):
        z = np.load(cache)
        mem_embs, q_embs, poi_embs = z["memories"], z["queries"], z["poison"]
        if len(poi_embs) != len(poisons):
            raise RuntimeError(f"stale cache {cache} — delete cache-adv-*")
    else:
        embedder = common.get_embedder()
        mem_embs = common.encode(embedder, [c["memory"] for c in calls])
        q_embs = common.encode(embedder, [c["query"] for c in calls], kind="query")
        poi_embs = (common.encode(embedder, [p[2] for p in poisons])
                    if poisons else np.zeros((0, mem_embs.shape[1]), np.float32))
        np.savez_compressed(cache, memories=mem_embs, queries=q_embs, poison=poi_embs)

    n_gen = len(calls)
    rows = [(i + 1, calls[i]["memory"], calls[i]["ts"]) for i in range(n_gen)]
    rows += [(n_gen + j + 1, poisons[j][2], poisons[j][1]) for j in range(len(poisons))]
    all_embs = np.concatenate([mem_embs, poi_embs]) if len(poisons) else mem_embs
    label_of = {i + 1: calls[i][label_key] for i in range(n_gen)}
    label_of.update({n_gen + j + 1: POISON for j in range(len(poisons))})
    poison_after = {n_gen + j + 1: poisons[j][0] for j in range(len(poisons))}
    poison_owner = {n_gen + j + 1: poisons[j][3] for j in range(len(poisons))}
    agent_of = {i + 1: f"actor:agent{i % args.agents}" for i in range(n_gen)}
    created_by = ([(i + 1, agent_of[i + 1]) for i in range(n_gen)]
                  + [(pid, poison_owner[pid]) for pid in poison_owner])
    attackers = [f"actor:attacker{i}" for i in range(n_attackers)]
    # Censorship targets: the 4 highest-volume labels (most worth suppressing).
    target_labels = set(sorted(
        i for i, _ in Counter(c[label_key] for c in calls).most_common(4)))
    if args.attack == "downvote":
        print(f"censorship targets: {sorted(target_labels)}", flush=True)

    stores = {c: common.MemoryStore(rows, all_embs) for c in CONDITIONS}
    for name, (excl, vote, trust) in DEFENSES.items():
        stores[name].set_created_by(created_by)
        if excl:
            stores[name].set_exclude_self(True)
        if vote:
            stores[name].set_one_vote(True)
        if trust:
            stores[name].set_trust(True, weighted=(trust == "weighted"))

    # Clean-store arm (no attacker at all) for the utility bars.
    clean_rows = rows[:n_gen]
    clean = {c: common.MemoryStore(clean_rows, mem_embs) for c in DEFENSES}
    for name, (excl, vote, trust) in DEFENSES.items():
        clean[name].set_created_by([(i + 1, agent_of[i + 1]) for i in range(n_gen)])
        if excl:
            clean[name].set_exclude_self(True)
        if vote:
            clean[name].set_one_vote(True)
        if trust:
            clean[name].set_trust(True, weighted=(trust == "weighted"))

    hits1 = defaultdict(list)
    hitsk = defaultdict(list)
    occ = defaultdict(list)
    clean_h1 = defaultdict(list)
    hits1_tgt = defaultdict(list)    # calls whose gold label is censored
    hits1_untgt = defaultdict(list)  # collateral check
    pumped = set()
    suppressed = defaultdict(set)   # cond -> memory ids already downvoted

    for ci in range(len(calls)):
        gold = calls[ci][label_key]
        now = calls[ci]["ts"]
        actor = agent_of[ci + 1]
        gen_prior = list(range(1, ci + 1))
        poi_prior = [m for m, after in poison_after.items() if after < ci]
        cands = gen_prior + poi_prior

        for cond in CONDITIONS:
            store = stores[cond]
            store.freeze(now)
            if cond != "sim":
                if args.attack in ("upvote", "collude"):
                    for pid in poi_prior:
                        if (cond, pid) in pumped:
                            continue
                        pumped.add((cond, pid))
                        # collude: every attacker EXCEPT the owner endorses,
                        # so no endorsement is self-endorsement.
                        boosters = ([a for a in attackers if a != poison_owner[pid]]
                                    if args.attack == "collude"
                                    else [poison_owner[pid]])
                        for booster in boosters:
                            for _ in range(args.pump):
                                store.record_accesses([pid], actor=booster)
                                store.record_outcomes([(pid, 1.0)], actor=booster)
                elif args.attack == "downvote":
                    # Targeted censorship: bury every genuine memory of the
                    # target labels, leaving the rest alone so the penalty is
                    # relative, not uniform.
                    targets = [m for m in gen_prior
                               if label_of[m] in target_labels
                               and m not in suppressed[cond]]
                    for m in targets:
                        suppressed[cond].add(m)
                        for _ in range(args.pump):
                            store.record_accesses([m], actor=attackers[0])
                            store.record_outcomes([(m, -1.0)], actor=attackers[0])
                store.freeze(now)
            rank_name = "sim" if cond == "sim" else "rfm_beta0.3"
            retrieved = common.rank(store, rank_name, q_embs[ci], cands, now, args.k)
            hit1 = bool(retrieved) and label_of[retrieved[0]] == gold
            hitsk[cond].append(any(label_of[m] == gold for m in retrieved))
            hits1[cond].append(hit1)
            occ[cond].append(sum(1 for m in retrieved if label_of[m] == POISON) / args.k)
            (hits1_tgt if gold in target_labels else hits1_untgt)[cond].append(hit1)
            if cond != "sim":
                store.record_accesses(retrieved, actor=actor)
                store.record_outcomes(
                    [(m, 1.0 if label_of[m] == gold else -1.0) for m in retrieved],
                    actor=actor)

        for cond in DEFENSES:
            store = clean[cond]
            store.freeze(now)
            if not gen_prior:
                continue
            retrieved = common.rank(store, "rfm_beta0.3", q_embs[ci], gen_prior,
                                    now, args.k)
            clean_h1[cond].append(bool(retrieved) and label_of[retrieved[0]] == gold)
            store.record_accesses(retrieved, actor=actor)
            store.record_outcomes(
                [(m, 1.0 if label_of[m] == gold else -1.0) for m in retrieved],
                actor=actor)

        if (ci + 1) % 500 == 0:
            print(f"{ci + 1}/{len(calls)}", flush=True)

    # Detector state must be read BEFORE the stores close.
    det = stores["rfm_trust"].collusion_signals()
    rep = stores["rfm_trust"].actor_trust()

    for s in list(stores.values()) + list(clean.values()):
        s.close()

    print(f"\n=== {args.dataset} adversary={args.attack} rate={args.rate} "
          f"pump={args.pump} attackers={n_attackers}, k={args.k}, "
          f"{common.EMBEDDER_ID} ===")
    print("| condition | legit hit@1 | legit hit@k | poison occupancy | clean-store hit@1 |")
    print("|---|---|---|---|---|")
    for cond in CONDITIONS:
        cl = f"{np.mean(clean_h1[cond]):.3f}" if cond in DEFENSES else "—"
        print(f"| {cond} | {np.mean(hits1[cond]):.3f} | {np.mean(hitsk[cond]):.3f} "
              f"| {np.mean(occ[cond]):.3f} | {cl} |")

    def paired(a_tab, a, b_tab, b):
        n = min(len(a_tab[a]), len(b_tab[b]))
        d = np.array(a_tab[a][-n:], float) - np.array(b_tab[b][-n:], float)
        lo, hi = common.bootstrap_ci(list(d))
        return f"{d.mean():+.4f} [{lo:+.4f},{hi:+.4f}] n={len(d)}"

    if args.attack == "downvote":
        print("\ncensored-label breakdown (hit@1 on targeted vs untargeted calls):")
        print("| condition | targeted | untargeted |")
        print("|---|---|---|")
        for cond in CONDITIONS:
            print(f"| {cond} | {np.mean(hits1_tgt[cond]):.3f} "
                  f"| {np.mean(hits1_untgt[cond]):.3f} |")

    print("\npre-registered endpoints:")
    print("  A1 attack hurts unhardened:  h@1 sim - rfm:      ",
          paired(hits1, "sim", hits1, "rfm"))
    if args.attack == "downvote":
        print("  A1t on TARGETED calls:       h@1 sim - rfm:      ",
              paired(hits1_tgt, "sim", hits1_tgt, "rfm"))
        for name in [d for d in DEFENSES if d != "rfm"]:
            print(f"  A2t {name:14s} targeted:   h@1 {name} - rfm: ",
                  paired(hits1_tgt, name, hits1_tgt, "rfm"))
    for name in [d for d in DEFENSES if d != "rfm"]:
        print(f"  A2 {name:14s} recovers:  h@1 {name} - rfm: ",
              paired(hits1, name, hits1, "rfm"))
        print(f"     {name:14s} vs sim baseline: h@1 {name} - sim: ",
              paired(hits1, name, hits1, "sim"))
    # Collusion detector (Amendment 8): dissent rate from the access log
    # alone, plus the writer-reputation table the trust cap already maintains.
    ranked = sorted(det.items(), key=lambda kv: -kv[1]["reciprocity"])
    is_attacker = set(attackers)
    print("\ncollusion detector (log-only forensics):")
    print("| actor | reciprocity | concentration | dissent | votes | writer trust | attacker? |")
    print("|---|---|---|---|---|---|---|")
    for a, sg in ranked[:10]:
        tv = rep.get(a, (float("nan"), 0))[0]
        print(f"| {a} | {sg['reciprocity']:.3f} | {sg['concentration']:.3f} "
              f"| {sg['dissent']:.3f} | {sg['votes']} | {tv:+.3f} "
              f"| {'YES' if a in is_attacker else 'no'} |")
    for signal in ("reciprocity", "concentration", "dissent"):
        order = sorted(det.items(), key=lambda kv: -kv[1][signal])
        flagged = {a for a, _ in order[:len(is_attacker)]}
        tp = len(flagged & is_attacker)
        att = [sg[signal] for a, sg in det.items() if a in is_attacker]
        hon = [sg[signal] for a, sg in det.items() if a not in is_attacker]
        sep = (np.mean(att) - np.mean(hon)) if att and hon else float("nan")
        print(f"  {signal:14s} precision@{len(is_attacker)} = "
              f"{tp}/{len(flagged)}  separation = {sep:+.3f}")

    print("\n  utility bars (clean store, no attacker present):")
    for name in [d for d in DEFENSES if d != "rfm"]:
        print(f"  U {name:14s} - rfm: ", paired(clean_h1, name, clean_h1, "rfm"))


if __name__ == "__main__":
    main()
