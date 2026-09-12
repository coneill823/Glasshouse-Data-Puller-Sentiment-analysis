# Representative grading (lexicon-based)

Grades every representative from the pulled data using simple, transparent word
lists — no machine learning. Four signals per representative:

1. **Tone** — positive/negative language across their questions & speeches.
2. **Topic stance** — a Pro/Con word list per policy category, applied to what
   they say (gated so a topic only scores when its keywords actually appear).
3. **Activity** — how much they participate (questions + speeches + votes).
4. **Voting** — each division motion is scored for topic + lean, then combined
   with how the member voted (aye/no) to give a voting stance per topic.

## Run

```bash
# after pulling data with main.py
python -m analysis.grade                 # grade everyone (current + historical)
python -m analysis.grade --current-only  # only sitting members
python -m analysis.grade --data-dir data --out analysis/output
```

Reads the cumulative `*_master.csv` files under `data/<parliament>/…` and joins
to `members_master.csv` for each member's party, constituency and status.

## Output (in `analysis/output/`)

`member_grades.csv` — one row per member:
`parliament, member, party, constituency, status, n_questions, n_speeches,
n_votes, activity_total, tone_score, topics_engaged, top_pro_topic, top_con_topic`

`member_topic_scores.csv` — one row per member × topic:
`… topic, mentions, spoken_pro, spoken_con, spoken_stance, vote_pro, vote_con,
vote_stance, combined_stance`

Stance columns run **-1 (con) … +1 (pro)**. Categories are named **`Pro-<topic>`**
so a positive score always means the member leans to that category's supportive
side (see `topics.py` for the axis of each — e.g. `Pro-Crime & justice` =
pro-law-and-order). `constituency` lets the app group by area (“show and grade the
representatives for my area”). Filter `status=current` for sitting members.

**How stance is scored:**
- `spoken_stance` / `vote_stance` / `combined_stance` = `(pro − con) / (pro + con + K)`
  with a shrink constant `K` (default 4), so **one hit doesn't saturate to ±1** —
  only strong, consistent evidence approaches the extremes.
- `combined_stance` is a **weighted** blend of the two signals present, with
  **votes weighted more than speech** (votes are unambiguous and negation-proof).
- `top_pro_topic` / `top_con_topic` are chosen only from topics with at least
  `MIN_STANCE_HITS` (default 3) pro+con hits, so a one-off blip can't win.
- Tune `STANCE_SHRINK_K`, `VOTE_WEIGHT`, `SPEECH_WEIGHT`, `MIN_STANCE_HITS` at the
  top of `grade.py`.

## Tuning

Everything gradeable lives in **`analysis/topics.py`** — edit it freely:

- `TOPICS[name]["keywords"]` decide when a statement is *about* a topic. Keep
  them specific; a too-generic keyword (e.g. bare "rights") creates false hits.
- `TOPICS[name]["pro"]` / `["con"]` define the stance axis for that topic. This
  is a political judgement — make the lists mean what you intend.
- `GENERAL_POSITIVE` / `GENERAL_NEGATIVE` drive the topic-independent tone score.

## Who gets graded

Members are canonicalised to the roster, so a person with both id-bearing and
name-only records is counted once (not duplicated). Speakers that aren't
gradeable members — the chair (`Mr Speaker`, `The Presiding Officer`, `Y
Llywydd`) and plenary parsing artifacts (`13:3`, `level 1`) — are excluded.
`--current-only` further restricts to sitting members. Note the artifacts still
exist in the raw plenary data; the grader just doesn't grade them.

## Caveats

- **Vote stance is heuristic**: it infers a motion's lean from its wording and
  combines it with the member's vote. Motions with neutral wording contribute
  nothing; genuinely mis-worded motions can mislead. Treat it as a signal.
- **Negation is partially handled**: a stance term is flipped if a negation cue
  ("not", "never", "against", "oppose"…) appears in the few tokens *before* it
  ("we will not fund the NHS" → con). But a *post-modified* attack ("net zero is
  a disaster") isn't caught — an inherent limit of lexicon scoring. This is why
  votes are weighted above speech. Sarcasm is likewise invisible.
- The final "grade" is intentionally left to the app: the CSVs expose the
  components (tone, activity, per-topic stance) so you can weight them however
  the product needs.
