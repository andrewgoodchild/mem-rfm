# What a bad team member can do to a shared memory

Once a memory store is shared, its ranking is something worth attacking. A
member who can write memories and rate them can, in principle, promote their
own content, bury someone else's, or coordinate with others to do both.

We measured four attacks and ten defence configurations across six
pre-registered amendments (PROTOCOL.md 5–10). As far as we know this is the
only quantified attack/defence evidence for memory ranking anywhere. Four of
those defences failed, which is the more useful half of the result.

Throughout: the attacker injects at 20% of traffic, results on STAR and ABCD,
"points" are percentage points of hit@1.

## Summary

| attack | unhardened | defended |
|---|---|---|
| **Write convincing junk** | self-correcting | inherent — the demotion loop |
| **Self-promote** | **worse than no ranking at all** | `exclude_self` — full recovery |
| **Censor a rival** | **fails outright** | none needed |
| **Collude** | **−5.0 points** | none works — detect instead |

---

## 1. Writing convincing junk

**The attack.** Write memories that look maximally relevant — bait copied
from real past queries — with a useless or wrong resolution attached. This is
the AgentPoison/MINJA regime, and no admission filter catches it, because
semantic similarity is exactly what the bait is optimised for.

**What happens.** Outcome ranking absorbs two-thirds to three-quarters of the
hit@1 damage. The interesting comparison is the shape rather than the size:
under plain similarity search the same fake gets served **29 times** and the
store's poison exposure *grows* over the stream; under outcome ranking it is
served **6 times** and exposure stays flat. Similarity never recovers,
because a fake that is semantically perfect stays semantically perfect. The
demotion loop is what makes junk decay instead of accumulating.

It still survives 20% sign-flipped feedback, which matters because real
outcome signals are noisy.

**Limit:** the defence is reactive. A bad memory gets served at least once
before there is any feedback to demote it.

## 2. Self-promotion

**The attack.** Inflate your own memories' standing using calls you are
entitled to make: retrieve them repeatedly to pump recency and frequency,
and rate them positively to pump the value axis.

**What happens without defence.** This is the one result that should worry
anyone running a usage prior on a shared store: **it becomes worse than
having no prior at all.** The gamed store served 6.8% junk against plain
similarity's 2.4%, and legitimate accuracy fell *below* the similarity
baseline — −1.5 points, and −9.8 under heavy gaming. The bounded prior caps
the damage but does not remove it.

Also measured: the **value axis is the softer target**. Gaming outcomes did
roughly three times the damage of gaming access counts, because activation is
logarithmic in use count (so extra accesses yield diminishing returns) while
the value EWMA saturates toward +1 within a few self-reports.

**The defence.** `rfm_config('exclude_self', 1)` — tag memories with a writer
(`created_by`) and pass the acting principal (`actor`), and the extension
ignores any access or outcome where the two match. A writer simply cannot
build their own memory's standing.

It works completely: recovery to 2.1 points *above* the similarity baseline,
poison exposure down to a quarter of similarity's, and the result is
**invariant to how hard the attacker games** — because the attack becomes a
no-op rather than a smaller effect. Cost on a healthy team store: nil.

**One caveat, measured:** on a *single-agent* store, where every memory is
self-authored, `exclude_self` discards **all** your feedback and costs −0.80
points. Leave it off unless the store genuinely has multiple writers. The
cost vanishes by two writers.

## 3. Censoring a rival

**The attack.** Don't write anything. Instead, systematically downvote
someone else's memories — or a whole procedure you want buried.

**What happens.** It fails outright. Not "is mitigated" — the censored
procedures scored **2.1 points better** under outcome ranking than under
plain similarity, and the attacked store's overall accuracy matched its
clean-store accuracy exactly.

**Why**, and this is the interesting part: the ranking multiplier is bounded
to [0.7, 1.0]. An attacker can demote a memory by at most 30%, and that is
smaller than the similarity gap between a right-label and a wrong-label
memory. There is no way to push a relevant memory below an irrelevant one.

A first attempt at this attack also produced a small lesson: downvoting
*everything* is mathematically a no-op, since a uniform penalty leaves
relative order unchanged. Only targeted suppression is even coherent, and
targeted suppression is what the bound defeats.

**The bound was adopted to stop the ranking being too influential, long
before anyone considered attacks. It turns out to be the thing that makes the
ranking unusable as a weapon.** Constraints on power cut both ways.

## 4. Collusion — the one that wins

**The attack.** Four members write bait and endorse *each other's*, so no
endorsement is ever self-endorsement.

**What happens.** −5.0 points, poison exposure tripled. And every defence
fails.

### Six failures, one explanation

| defence | idea | result |
|---|---|---|
| `exclude_self` | ignore self-endorsement | blind by construction — nobody endorses their own |
| `one_vote` | one outcome per (actor, memory) | **backfires**, see below |
| `one_vote` + `trust` | combine the two | significantly **negative** on both datasets |
| `trust` | cap a memory's value at its author's reputation | fails — see below |
| `trust_weighted` | weight a vote by the voter's own standing (EigenTrust-style) | no recovery |
| `endorser_liability` | make vouching cost the voucher | partial; see below |

They fail for one reason. **Every one of them aggregates votes, and a ring
manufactures votes.** Moving the aggregation from memories to authors to
voter-weights just moves the attack up a level with it. This is the same
reason cleverer averaging does not solve Sybil attacks: escaping it requires
something outside the vote graph — identity cost, pre-trusted seeds, or a
human decision.

Two failures are worth understanding individually.

**`one_vote` (ballot-stuffing prevention) backfires.** Capping each person to
one vote per memory sounds obviously right. It defends nothing measurable and
costs −0.34 points on a clean store, because **it throttles the corrective
signal exactly as hard as the abusive one**. Unhardened, a bad memory earns a
negative every single time it wastes someone's time — that is what makes
demotion converge. Capped, an eight-person team can land at most eight
negatives on it, ever. You ration the immune response along with the
infection. It ships off by default, documented as not recommended, with the
measurement behind that judgement.

The general lesson: **asymmetric defences beat symmetric caps.**
`exclude_self` works because it removes an *illegitimate* signal; `one_vote`
fails because it rations a legitimate one.

**Writer reputation (`trust`) fails because reputation launders too.** Cap a
memory's value at its author's third-party reputation, and a ring simply
builds each other's reputation — their cross-endorsements *are* third-party
votes. Measured: a ring member's trust came out at +0.400 while an honest
agent sat at −0.314. Reputation is just another vote aggregate.

Worth noting: `trust` is genuinely useful against *single* bad actors — a
lone attacker cannot build their own reputation — and `exclude_self` + `trust`
is the best measured configuration for that case.

### The prisoner's dilemma: making collusion individually irrational

The last attempt gave up on out-counting the ring and went after its
incentives instead.

Ordinarily, endorsing a memory is free — you vouch for it, and if it later
fails, nothing happens to you. **`rfm_config('endorser_liability', 1)`
changes that: an outcome on a memory is folded into the reputation of every
prior positive endorser, not just its author.** Vouching becomes a stake.

That creates a genuine dilemma for a ring, because it loses on both branches:

- **Cooperate** (keep cross-endorsing): every failed retrieval of a
  co-conspirator's bait now debits the endorser as well as the author. A ring
  member who vouches for hundreds of baits absorbs hundreds of negatives on
  top of their own failures, so ring standing collapses *faster* than a solo
  attacker's — and the trust cap then buries their content.
- **Defect** (stop endorsing): the bait keeps only its author's own votes,
  which `exclude_self` already nullifies. The attack degenerates into the
  solo case, which is fully defended.

Crucially it does not repeat `one_vote`'s mistake: honest endorsement is safe
by asymmetry rather than exemption. Agents endorse memories that helped them,
those memories tend to help others, and the endorser is repaid.

**What we measured.** The incentive mechanism works exactly as theorised *at
the reputation layer*, on both datasets: ring standing collapses to −0.734
and −0.981 while honest agents rise to +0.950 and +0.714 — roughly double the
separation plain reputation achieves. It is free on a clean store.

**But it does not repair retrieval.** The recovery was +0.8 points on one
dataset and null on the other — it did not replicate. Bait that was served
*before* the ring's standing collapsed is damage no post-hoc mechanism can
undo.

So liability is a real and free adjunct that makes a ring **costly and
identifiable**. It is not a fix.

### What does work: detection

You cannot out-rank a ring. You can spot one.

A colluding ring praises only its own members, and that **concentration** is
a signal it cannot manufacture without dismantling the ring. It identified
all four colluders on both datasets, using nothing but the access log.

Two more intuitive detectors were tried and both failed, which is worth
knowing before you build one:

- **Disagreement with consensus inverts.** A ring that stuffs ballots
  *becomes* the consensus, so the detector flags the honest majority instead.
  Precision 0/4, separation negative.
- **Reciprocity has no signal.** Honest teammates also endorse each other's
  memories in the normal course of work. Mutual endorsement isn't suspicious;
  it's what a functioning team looks like.

Run [`integrations/audit.sql`](../integrations/audit.sql) against a store for
writer reputation, endorsement concentration and mutual-endorsement pairs,
plus governance actions — quarantine, freeze, revoke, scope erasure — written
out as explicit SQL.

Those are deliberately **manual**. Automatically acting on a detector is its
own attack surface: one false positive silently deletes an honest
colleague's work, and an attacker who understands your detector can aim it.

## Practical guidance

**For a shared store:** turn on `exclude_self` and `trust`. Optionally add
`endorser_liability`, which is free and makes rings identifiable. Do not turn
on `one_vote`.

**For a single-agent store:** leave all of them off. `exclude_self` would
discard every piece of feedback you have.

**The trust boundary is the deployment boundary.** If your writers are
colleagues or systems you operate, this is genuinely resistant: the attacks
that actually happen — one careless member, one compromised credential, stale
content — are the ones fully handled, and collusion needs several coordinated
insiders, at which point memory ranking is not your biggest problem. If your
writers are anonymous, do not run a usage prior at all; there a ring is the
default case rather than the exotic one.

**Everything here is reactive.** There is no admission control. Damage before
detection is real, and no mechanism in this repo recovers it.
