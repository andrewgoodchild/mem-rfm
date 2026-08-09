-- Shared-store audit: who is behaving badly, and what to do about it.
--
--   sqlite3 memory.db ".read integrations/audit.sql"
--
-- Pure forensics over the committed log — no scoring state is read or
-- written, so this is safe to run on a copy, and its answers are
-- reproducible by anyone holding the same database. Only meaningful on a
-- store whose writers are tagged (created_by / actor); an untagged
-- single-user store has nobody to distinguish.
--
-- The measured basis for these queries is PROTOCOL.md Amendments 5-10 and
-- the RESULTS.md entries for them. The headline finding they exist to serve:
-- a colluding ring cannot be defeated by ranking (six mechanisms were tried
-- and none restored the baseline), but it CAN be identified — the
-- concentration signal below reached 4/4 precision on two datasets.

.mode column
.headers on

-- 1. WRITER REPUTATION ------------------------------------------------------
-- Third-party outcomes on each actor's memories (their own votes excluded by
-- the extension). Consistently negative = their memories waste other people's
-- retrievals. Populated only when rfm_record_outcome is called with an actor.
SELECT 'writer reputation' AS report;
SELECT a.actor,
       round(a.value_score, 3) AS trust,
       a.outcome_count         AS judged,
       (SELECT count(*) FROM rfm_memories m WHERE m.created_by = a.actor) AS wrote
FROM rfm_actors a
ORDER BY a.value_score ASC;

-- 2. ENDORSEMENT CONCENTRATION (the collusion signal) -----------------------
-- For each voter: how many DISTINCT authors receive their positive outcomes,
-- and what share goes to their single most-praised author. A ring praises
-- only its own members, so `top_share` runs high and `authors_praised` low,
-- while honest agents praise whoever happened to write the useful memory.
--
-- Two intuitive alternatives were measured and FAILED (RESULTS.md,
-- Amendment 8): disagreement-with-consensus INVERTS, because a ring that
-- stuffs ballots becomes the consensus and the detector then flags the
-- honest majority; and reciprocity shows no separation at all, because
-- honest teammates also endorse each other in the normal course of work.
-- Concentration works because it is the one signal a ring cannot manufacture.
SELECT 'endorsement concentration (high top_share + low authors_praised = suspicious)' AS report;
WITH praise AS (
  SELECT acc.actor AS voter, m.created_by AS author, count(*) AS n
  FROM rfm_accesses acc JOIN rfm_memories m ON m.id = acc.memory_id
  WHERE acc.outcome > 0 AND acc.actor IS NOT NULL
    AND m.created_by IS NOT NULL AND m.created_by <> acc.actor
  GROUP BY acc.actor, m.created_by
)
SELECT voter,
       count(*)                                   AS authors_praised,
       sum(n)                                     AS endorsements,
       round(max(n) * 1.0 / sum(n), 3)            AS top_share
FROM praise GROUP BY voter ORDER BY top_share DESC, authors_praised ASC;

-- 3. MUTUAL ENDORSEMENT PAIRS ----------------------------------------------
-- Ranked pairs who endorse each other. NOT evidence on its own — honest
-- teammates reciprocate too (measured: no separation) — but useful for
-- reading the shape of a ring once concentration has flagged its members.
SELECT 'mutual endorsement pairs' AS report;
WITH praise AS (
  SELECT acc.actor AS voter, m.created_by AS author, count(*) AS n
  FROM rfm_accesses acc JOIN rfm_memories m ON m.id = acc.memory_id
  WHERE acc.outcome > 0 AND acc.actor IS NOT NULL
    AND m.created_by IS NOT NULL AND m.created_by <> acc.actor
  GROUP BY acc.actor, m.created_by
)
SELECT p.voter, p.author, p.n AS praised, q.n AS praised_back
FROM praise p JOIN praise q ON q.voter = p.author AND q.author = p.voter
WHERE p.voter < p.author
ORDER BY (p.n + q.n) DESC LIMIT 20;

-- 4. GOVERNANCE ------------------------------------------------------------
-- Ranking cannot evict a ring; a human decision can. These are the actions,
-- deliberately left as explicit statements rather than shipped automation —
-- an automated response to a detector is itself an attack surface (a false
-- positive silently deletes an honest colleague's work).
--
-- QUARANTINE — stop an actor's memories from being retrieved, keeping the
-- evidence intact. Add to your retrieval WHERE clause:
--     AND (created_by IS NULL OR created_by NOT IN (SELECT actor FROM rfm_quarantine))
-- CREATE TABLE IF NOT EXISTS rfm_quarantine(actor TEXT PRIMARY KEY, reason TEXT, at REAL);
-- INSERT INTO rfm_quarantine VALUES ('actor:mallory', 'ring: concentration 0.75', unixepoch());
--
-- FREEZE — stop trusting an actor's votes going forward: the host simply
-- stops passing their outcomes to rfm_record_outcome. Nothing to run here.
--
-- REVOKE — irreversible removal of an actor's memories and their history.
-- Read the rows first; this cannot be undone.
--     SELECT id, content FROM rfm_memories WHERE created_by = 'actor:mallory';
--     DELETE FROM rfm_accesses WHERE memory_id IN
--       (SELECT id FROM rfm_memories WHERE created_by = 'actor:mallory');
--     DELETE FROM rfm_memories WHERE created_by = 'actor:mallory';
--     DELETE FROM rfm_actors  WHERE actor = 'actor:mallory';
--
-- SCOPE ERASURE — when a whole scope must go, delete its database file. One
-- DB per scope is the recommended layout precisely so this is possible.
