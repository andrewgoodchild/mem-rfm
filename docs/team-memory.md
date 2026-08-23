# Team memory: what we measured, why it looked promising, and why we stopped

This is a record of an exploration that we closed. It is the longest document
in this repo because the result was negative in an interesting way: the
mechanism works, the numbers are large and replicated, and we still concluded
it should not be built.

Three things killed it, in increasing order of importance:

1. **A shared store is an attack surface**, and the hardest attack has no
   fix at the ranking layer.
2. **The infrastructure a real team store needs** is a different project from
   a scoring primitive.
3. **The market has already run this experiment**, repeatedly, and the
   results are not encouraging.

The code that produced every number below is preserved at the
**`archive/team-experiments`** git tag. It was removed from `main` afterwards to keep
the shipped primitive small.

---

## 1. Why pooling should work

Memory pays where work **recurs** ([findings](findings.md)). Anything that
multiplies recurrence should multiply memory's value — and sharing a store
across agents does exactly that. Eight agents working one domain collectively
see each situation roughly eight times as often as any of them does alone.
One agent's solved problem becomes everyone's candidate memory.

That is a clean hypothesis, and it is straightforwardly testable.

## 2. What we measured — and it looks great

Four datasets: one exploratory, then three **pre-registered replications**
(PROTOCOL.md Amendment 4, with endpoints and falsification criteria committed
before the runs).

| dataset | domain | shared vs per-agent stores (hit@5) |
|---|---|---|
| STAR | task-oriented dialog, **115 real human agents** | **+26.1** [+24.7, +27.5] |
| MultiDoc2Dial | government-policy Q&A | **+37.5** [+35.9, +39.1] |
| FloDial | technical troubleshooting | **+4.0** [+3.2, +5.0] |
| ABCD | customer support (exploratory) | **+14.5** [+13.0, +16.1] |

STAR carries the most weight: its split follows the dataset's own 115 human
wizards on the real collection timeline, so neither the grouping nor the
ordering is our construction — the two weakest points of the original ABCD
result. FloDial's small effect is a ceiling, not a failure: with only 10
distinct procedures a solo agent sees everything quickly, so pooling has
little left to add. The benefit tracks how much recurrence an individual is
*missing*.

**Pooled experience also beat each dataset's authored manual** — the "just do
RAG over the documentation" baseline — by 12.0 / 21.1 / 6.4 / 1.7 points at
hit@1. But the manual owns the cold start decisively: on MultiDoc2Dial's
first 500 interactions, having it is worth **+42.6 points**. The best
configuration everywhere was all three layers: manual for day one,
accumulated experience for depth, outcomes for maintenance.

A caveat that cuts against us: a stronger embedding model narrows the
experience-versus-manual gap considerably (STAR: +21.1 → +6.0), because clean
authored prose benefits more from better embeddings than messy experience
text does.

**On the surface, this is a strong result.** Large effects, replicated,
pre-registered, on data with real human agents. Everything below is why that
wasn't enough.

---

## 3. The first catch: a shared store is worth attacking

Once a store is shared, its ranking becomes something a contributor can
manipulate. We ran six pre-registered amendments (PROTOCOL.md 5–10) covering
four attacks and ten defence configurations. As far as we know this remains
the only quantified attack/defence evidence for memory ranking anywhere —
and four of the ten defences failed.

Throughout: the attacker injects at 20% of traffic, results on STAR and ABCD,
"points" are percentage points of hit@1.

| attack | unhardened | defended |
|---|---|---|
| **Write convincing junk** | self-correcting | inherent — the demotion loop |
| **Self-promote** | **worse than no ranking at all** | `exclude_self` — full recovery |
| **Censor a rival** | **fails outright** | none needed |
| **Collude** | **−5.0 points** | none works — detect instead |

### 3.1 Writing convincing junk

Bait copied from real past queries, with a useless resolution attached — the
AgentPoison/MINJA regime, which no admission filter catches because semantic
similarity is exactly what the bait optimises for.

Outcome ranking absorbs two-thirds to three-quarters of the damage. The
shape matters more than the size: under plain similarity the same fake is
served **29 times** and poison exposure *grows* over the stream; under
outcome ranking it is served **6 times** and exposure stays flat. Similarity
never recovers, because a semantically perfect fake stays semantically
perfect. The defence survives 20% sign-flipped feedback.

Limit: it is reactive. A bad memory is served at least once before there is
feedback to demote it.

### 3.2 Self-promotion

Inflate your own memories using calls you are entitled to make: retrieve them
repeatedly to pump recency and frequency, self-rate them to pump value.

Without defence this is the result that should worry anyone running a usage
prior on a shared store: **it becomes worse than having no prior at all.**
The gamed store served 6.8% junk against plain similarity's 2.4%, and
legitimate accuracy fell *below* the similarity baseline — −1.5 points, and
−9.8 under heavy gaming.

The **value axis is the softer target**: gaming outcomes did roughly three
times the damage of gaming access counts, because activation is logarithmic
in use count while the value EWMA saturates toward +1 within a few
self-reports.

`exclude_self` — ignore any access or outcome where the actor equals the
memory's writer — fixes it completely: recovery to 2.1 points *above* the
similarity baseline, exposure down to a quarter of similarity's, and the
result is **invariant to how hard the attacker games**, because the attack
becomes a no-op rather than a smaller effect.

One measured caveat: on a *single-agent* store, where every memory is
self-authored, `exclude_self` discards **all** feedback and costs −0.80
points. The cost vanishes by two writers.

### 3.3 Censorship fails structurally

Systematically downvoting a rival's memories — or a whole procedure you want
buried — does not work. The censored procedures scored **2.1 points better**
under outcome ranking than under plain similarity, and the attacked store's
accuracy matched its clean-store accuracy exactly.

Why: the ranking multiplier is bounded to [0.7, 1.0]. An attacker can demote
by at most 30%, which is smaller than the similarity gap between a
right-label and a wrong-label memory. There is no way to push a relevant
memory below an irrelevant one.

**The bound was adopted to stop the ranking being too influential, long
before anyone considered attacks. It turns out to be what makes the ranking
unusable as a weapon.** Constraints on power cut both ways.

(A first attempt also produced a small lesson: downvoting *everything* is
mathematically a no-op, since a uniform penalty leaves relative order
unchanged.)

### 3.4 Collusion — the one that wins

Four members write bait and endorse *each other's*, so no endorsement is ever
self-endorsement. Result: −5.0 points, poison exposure tripled, and every
defence fails.

| defence | idea | result |
|---|---|---|
| `exclude_self` | ignore self-endorsement | blind — nobody endorses their own |
| `one_vote` | one outcome per (actor, memory) | **backfires** |
| `one_vote` + `trust` | combine them | significantly **negative** on both datasets |
| `trust` | cap a memory's value at its author's reputation | fails — reputation launders too |
| `trust_weighted` | weight a vote by the voter's standing (EigenTrust-style) | no recovery |
| `endorser_liability` | make vouching cost the voucher | partial — see below |

They fail for one reason: **every one of them aggregates votes, and a ring
manufactures votes.** Moving aggregation from memories to authors to
voter-weights moves the attack up with it. Escaping that requires something
outside the vote graph — identity cost, pre-trusted seeds, or a human
decision.

Two failures are worth understanding individually.

**`one_vote` backfires.** Capping each person to one vote per memory sounds
obviously right. It defends nothing measurable and costs −0.34 points on a
clean store, because **it throttles the corrective signal exactly as hard as
the abusive one**. Unhardened, a bad memory earns a negative every time it
wastes someone's time — that is what makes demotion converge. Capped, an
eight-person team can land at most eight negatives on it, ever. You ration
the immune response along with the infection.

The general lesson: **asymmetric defences beat symmetric caps.**
`exclude_self` works because it removes an *illegitimate* signal; `one_vote`
fails because it rations a legitimate one.

**Writer reputation fails because reputation launders too.** Cap a memory's
value at its author's third-party reputation and a ring simply builds each
other's reputation — their cross-endorsements *are* third-party votes. A ring
member's trust came out at +0.400 while an honest agent sat at −0.314.

### 3.5 The prisoner's dilemma

The last attempt gave up on out-counting the ring and went after its
incentives.

Ordinarily endorsement is free: vouch for a memory, and if it later fails,
nothing happens to you. **Endorser liability changes that — an outcome on a
memory is folded into the reputation of every prior positive endorser, not
just the author.** Vouching becomes a stake.

That puts a ring in a genuine dilemma, losing on both branches:

- **Cooperate** (keep cross-endorsing): every failed retrieval of a
  co-conspirator's bait debits the endorser as well as the author. A ring
  member vouching for hundreds of baits absorbs hundreds of negatives on top
  of their own failures, so ring standing collapses *faster* than a solo
  attacker's — and the trust cap then buries their content.
- **Defect** (stop endorsing): the bait keeps only its author's own votes,
  which `exclude_self` already nullifies. The attack degenerates into the
  solo case, which is fully defended.

Crucially it does not repeat `one_vote`'s mistake: honest endorsement is safe
by asymmetry rather than exemption. Agents endorse memories that helped them,
those memories tend to help others, and the endorser is repaid.

**Measured:** the incentive works exactly as theorised *at the reputation
layer*, on both datasets — ring standing collapses to −0.734 and −0.981 while
honest agents rise to +0.950 and +0.714, roughly double the separation plain
reputation achieves. It is free on a clean store.

**But it does not repair retrieval.** Recovery was +0.8 points on one dataset
and null on the other — it did not replicate. Bait served *before* the ring's
standing collapses is damage no post-hoc mechanism can undo.

So liability makes a ring costly and identifiable. It is not a fix.

### 3.6 Detection works where ranking cannot

A colluding ring praises only its own members, and that **concentration** is
a signal it cannot manufacture without dismantling the ring. It identified
all four colluders on both datasets from the access log alone.

Two intuitive alternatives failed, and their failures are the transferable
part:

- **Disagreement with consensus inverts.** A ring that stuffs ballots
  *becomes* the consensus, so the detector flags the honest majority.
- **Reciprocity has no signal.** Honest teammates also endorse each other in
  the normal course of work.

**Prior-art correction, important.** This detector is **not novel**, and we
initially claimed too much for it. Endorsement concentration is a lightweight
per-node approximation of published statistics: CatchSync (Jiang et al., KDD
2014) defines the same object — closeness among a contributor's endorsement
targets — and pairs it with a background-correction term ours lacks, so ours
will fire on anyone who legitimately specialises. FRAUDAR (Hooi et al., KDD
2016) names its Axiom 4 "Concentration". Ye & Akoglu (ECML/PKDD 2015) is the
entropy formulation, computed item-side where ours is contributor-side.

Worse, **the shipped form has a proven evasion.** FRAUDAR Theorem 3 proves
row-normalised density metrics are not camouflage-resistant, and
per-contributor concentration is row-normalised: a ring that also endorses
some honest memories raises its own entropy and drops its score, at zero cost
to the attack. The known fix is a column-weighted block density (FRAUDAR's
greedy peel, ~20 lines, O(|E| log |V|)), which we did not implement.

Also: our "reciprocity has no signal" result reproduces a lesson the
recommender-systems field learned three times independently. It is a sanity
check, not a contribution.

Finally, our evaluation regime sits outside the validated one. Published
group-shilling numbers come from synthetic profiles at 2–14% attack size on
1000+ user datasets; a 4-member ring in a small team is far below that, with
a much higher base rate of legitimately correlated behaviour. Our clean 4/4
separation is two datasets at one ring size and should not be generalised.

**Newer threat worth noting:** the Salami Attack / MemCollusion
(arXiv:2608.01637, Aug 2026) composes individually-benign memory fragments
into collectively harmful ones — 75% attack success, explicitly robust to
benign dilution and memory-level defences. That is the modern version of this
problem and nothing here addresses it.

---

## 4. The second catch: the infrastructure isn't a scoring problem

What works today is one SQLite file, one server process, several agents. That
is a genuine shared store and it is what the measurements model.

What does not exist, and is not a small amount of work:

- **No cross-machine sync.** SQLite is a local file; network filesystems are
  a bad idea for SQLite writes.
- **No access control.** Anything connected reads everything. Scoping is a
  convention, not a boundary.
- **No admission control.** Nothing inspects a memory before storage; the
  defence model is entirely post-hoc.
- **No multi-writer conflict handling**, no identity verification (actor
  strings are host-asserted), no automated response to detection.

Each is tractable. Together they are a service with an auth surface, an abuse
story, an on-call implication, and other people's data in it — a different
project from a SQLite extension.

---

## 5. The third catch: the market has run this experiment

This is what actually closed the question. Surveying ~35 products and the
developer community in August 2026:

**Vendors who tried auto-learned shared memory retreated from it.**

- **Cursor shipped Memories and killed it** in 2.1.x. Staff stated the
  rationale plainly: memories "are almost no different than .mdc files."
  Users were told to export and convert to Rules.
- **Anthropic built auto-memory and deliberately firewalled it.** The docs
  state it is machine-local, "not shared across machines or cloud
  environments," and route team sharing to committed CLAUDE.md. The vendor
  with the best view of demand chose not to share it.

**Two independent teams tried admission gating and abandoned it.**

- **Tencent** (TencentDB Agent Memory) had a three-gate quality filter in v1;
  measured against their own known-good set it captured only **18 of 39
  (46%)**, so they deleted all three gates and flipped the default from "when
  in doubt, silence" to "when in doubt, capture."
- **Cognee** ships genuine outcome-feedback ranking and defaults its
  influence to **zero**.

Aggressive gating destroys recall, and nobody has a principled way to bound
that trade-off. (That, incidentally, is what β-bounding is — the one part of
this project that addresses the hard problem directly.)

**Governance is frequently theatre.** Tencent has the best access-control
model surveyed — allow/deny ACL rows, four visibility levels, a `reviewer`
role — but `AssetStatus` includes `approved` and **no code path ever sets
it**, and the `reviewer` role only hides a nav item. It stores
`usage_count`, `last_used_at`, `confidence` and `expires_at` and reads none
of them at retrieval.

**The demand simply isn't there.**

- Claude Code's "Shared Team Memory" request: **10 👍, zero maintainer
  response in 4.5 months**. Its "Support AGENTS.md" request: **4,564 👍**.
  Developers want one committed file, not a learned store.
- Every dedicated team-memory project is dead: 21, 21, 27 (archived), 9, 1
  stars. Individual memory tools in the same window: 633, 26k, 63k, 90k.
- The most-starred memory tool in the space (claude-mem, ~90k) is
  deliberately **single-user**. The adoption leaders by downloads (Mem0,
  Supermemory) don't do team pooling at all.
- The one lively feature thread is **supply, not demand**: at least 8 of 26
  comments are founders pitching their own products, several opening with
  "Full disclosure: I built…". Almost nobody says "I have this problem too."
- Of ~35 products, exactly one (Caura, ~430 stars) ships pooled memory +
  outcome ranking + access control + admission review. A real gap, in a
  market with no buyers.

**And independent work replicates our negative result.** An ETH Zurich study
(arXiv:2602.11988) tested context files across SWE-Bench Lite and 138 tasks
in 12 repositories: LLM-generated context files **reduced** success ~3% and
raised cost over 20%; developer-written ones helped ~4% while still costing
up to 19% more. Value appeared only when repository docs were stripped — it
was redundant pre-caching. Different group, different tasks, same conclusion
as our live A/B.

---

## 6. Why we stopped

The mechanism works. The numbers are real and replicated. And:

- the hardest attack on a shared store has no fix at the ranking layer, only
  detection and human governance;
- the missing infrastructure is a service, not a feature;
- every vendor that tried the product retreated, organic demand is ~450×
  below the alternative developers actually ask for, and every open-source
  attempt is dead.

Shipping this would have meant being the best implementation of a thing
nobody buys. The measurements stay, because "pooling improves retrieval" is
true and worth knowing. The product doesn't, because "someone will use it"
isn't.

If you want to build on it anyway, the honest starting points are: pool
delexicalized patterns rather than transcripts, keep per-user context in
per-scope stores, use one database file per scope so erasure is deleting a
file, and read §3 before you let anyone you don't employ write to it.

## 7. Reproducing any of this

The extension flags (`exclude_self`, `one_vote`, `trust`, `trust_weighted`,
`endorser_liability`), the `rfm_actors` reputation table, the actor-tagging
columns, the adversarial harnesses and the audit queries all live at the
**`archive/team-experiments`** tag:

```sh
git checkout archive/team-experiments
cargo build --release
cd bench-quality && python adversary_eval.py --dataset star --attack collude
```

Per-call outputs and full logs for every run are committed under
`bench-quality/`, and the pre-registrations are PROTOCOL.md Amendments 4–10.
