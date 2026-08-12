# Team memory: what we measured, and what actually ships

This is the part of mem-rfm with the largest measured effect and the
smallest amount of engineering behind it. Both halves of that sentence
matter, so this document covers the evidence first and the honest state of
the implementation second.

## Why pooling should help

Memory pays where work **recurs**. That is the single finding everything else
rests on ([findings](findings.md)). It follows that anything multiplying
recurrence should multiply the value of memory — and sharing a store across
several agents does exactly that. Eight agents working the same domain see
each situation roughly eight times as often, collectively, as any one of them
does alone. One agent's solved problem becomes everyone else's candidate
memory.

## What we measured

Four datasets: one exploratory, then three **pre-registered replications**
(PROTOCOL.md Amendment 4 — endpoints and falsification criteria committed
before the runs).

| dataset | domain | shared vs per-agent stores (hit@5) |
|---|---|---|
| STAR | task-oriented dialog, **115 real human agents** | **+26.1** [+24.7, +27.5] |
| MultiDoc2Dial | government-policy Q&A | **+37.5** [+35.9, +39.1] |
| FloDial | technical troubleshooting | **+4.0** [+3.2, +5.0] |
| ABCD | customer support (exploratory) | **+14.5** [+13.0, +16.1] |

STAR carries the most weight. Its split follows the dataset's own 115 human
wizards on the real collection timeline, so neither the grouping into agents
nor the ordering of the stream is our construction — the two weakest points
of the original ABCD result.

FloDial's small effect is not a failure but a ceiling: with only 10 distinct
procedures, a solo agent already sees everything quickly, so there is little
left for pooling to add. The size of the pooling benefit tracks how much
recurrence an individual agent is *missing*.

### Pooled experience beats the authored manual

Each dataset ships a real human-written manual — the "just do RAG over the
documentation" baseline. Accumulated experience out-ranks it at hit@1 by
**12.0 / 21.1 / 6.4 / 1.7** points across the four datasets.

But the manual owns the cold start decisively. On MultiDoc2Dial's first 500
interactions, having the manual is worth **+42.6 points** over experience
alone — an empty experience store knows nothing, and a document written by
someone who understood the domain knows a great deal.

The best configuration everywhere was all three layers together:

**manual for day one → accumulated experience for depth → outcomes for
maintenance.**

A caveat that cuts against us: a stronger embedding model narrows the
experience-versus-manual gap considerably (on STAR, from +21.1 to +6.0),
because clean authored prose benefits more from better embeddings than messy
experience text does. Experience still wins, but the margin depends on your
retriever.

### Where outcome ranking earns its place

Pooling is a coverage effect and doesn't need the value axis — plain
similarity over a shared store gets most of it. The value axis contributes
two things pooling alone does not:

- **Staleness recovery.** After a simulated procedure change, similarity-only
  retrieval kept recommending the dead procedure 1,500 calls later (hit@1
  0.20 versus 0.76 before the change), because a stale entry stays
  semantically perfect forever. With outcome feedback driving demotion, the
  recovery curve beats it in every bin, ending at 0.56 versus 0.20. *(One
  dataset, exploratory, never pre-registered — the weakest headline result
  here.)*
- **Defence.** A shared store is a shared attack surface, and the value axis
  is what makes bad content decay rather than persist. See
  [adversarial](adversarial.md).

---

## How a team would actually run this

Here is the honest state of it. **The experiments model a single shared
store. mem-rfm ships the scoring for that store and very little of the
infrastructure around it.**

### What works today

One SQLite file, one server process, several agents:

```sh
# on a shared host
RFM_MEMORY_DB=/srv/memory/team.db \
RFM_ACTOR=agent:alice \
RFM_HARDEN=exclude_self,trust \
  python integrations/claude-code/server.py
```

Each agent connects to an MCP server pointed at the same database. The server
process serialises writes, SQLite's WAL mode handles concurrent reads, and
`RFM_ACTOR` tags who wrote and who voted — which is what the hardening flags
and the audit queries need.

This is a genuine shared store and it is what the measurements above model.
For a team of agents on one machine, or several developers' agents against
one internal host, it works now.

### What does not exist

Be clear-eyed about the gap between "a shared file" and "team memory as a
product":

- **No cross-machine synchronisation.** SQLite is a local file. Agents on
  different laptops cannot share a store without putting it behind a network
  service themselves. Network filesystems are a bad idea for SQLite writes.
- **No access control.** Anything connected to the store can read every
  memory in it and write new ones. Scoping is a *convention* (one database
  file per scope), not an enforced boundary.
- **No admission control.** Nothing inspects a memory before it is stored.
  The defence model is entirely post-hoc: bad content gets demoted after it
  has been retrieved and failed.
- **No multi-writer conflict handling.** One writer at a time, by process.
- **No identity verification.** `RFM_ACTOR` is whatever the host asserts. The
  hardening defends against a principal misbehaving within its rights, not
  against impersonation — that belongs to your auth layer.
- **No automated response to detection.** The audit queries identify bad
  actors; acting on them is a human decision, deliberately.

### If you wanted to build it

The plausible routes, roughly in order of effort — none of these are
implemented, and none have been measured:

1. **Server-fronted store** (smallest step). Put the existing MCP server on a
   host, give each agent an `RFM_ACTOR`, and add authentication in front. You
   get the measured behaviour and a real trust boundary, at the cost of
   running a service.
2. **libSQL / Turso.** SQLite-compatible with a server mode and replication,
   and it can load extensions — the closest thing to "the same thing but
   networked."
3. **Replication or CRDT sync** for local-first operation, where each agent
   keeps a local store that syncs. mem-rfm is unusually well-suited to this:
   because exactly one outcome is recorded per access, the access log fully
   reproduces the summary state, so two peers' logs can in principle be merged
   and replayed to converge deterministically. That is a real property, not a
   plan — nothing implements it.
4. **A Postgres port** of the scoring functions, if your team's data already
   lives there.

Design notes on the P2P direction, including a trust model and the
open problems, are sketched but unbuilt.

### Privacy, if you do pool

The measurements say pooling is worth engineering for. They say nothing about
whether *your* data should be pooled. If you build on this:

- Pool **delexicalized patterns**, not transcripts. What recurs across a team
  is the shape of a problem and its resolution, not any individual's content.
- Keep customer- or user-specific context in **per-scope stores**, where its
  recurrence actually lives.
- Use **one database file per scope**, so that erasure is deleting a file
  rather than a query you have to trust.

## Honest summary

Pooling produces the largest and best-replicated effect in this project. It
is also the part where mem-rfm is a scoring primitive rather than a system:
you get the ranking, the identity tagging, the hardening flags and the audit
tooling, and you supply the service, the auth, and the sync.

If someone tells you they have team agent memory solved, the questions worth
asking are the ones in the "what does not exist" list above. As of the survey
in this repo, no shipping system answers all of them either — but that is not
a reason to overstate what this one does.
