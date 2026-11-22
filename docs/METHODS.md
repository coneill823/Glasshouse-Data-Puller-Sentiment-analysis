# How Glasshouse assesses a representative

Glasshouse answers two questions about each sitting MP, MSP, MS and MLA:

1. **What did they do?** — a factual record: turnout, breaks with their party,
   what they spend their time on.
2. **How closely do their votes match your views?** — a quiz, a match
   percentage, and a compass position. House of Commons only, for now.

This document sets out every way a representative's political leaning can be
assessed, which of them Glasshouse uses, and why. Sources and endpoints were
last checked on 2026-11-22.

## The principle: actions over words

Evidence is ranked by how directly the act changes policy. The more direct the
act, the more it counts; below a certain point it is reported but never scored.

| Rank | Act | Why it ranks here | How Glasshouse uses it |
|---|---|---|---|
| 1 | **Vote that uses Parliament's powers** — a bill stage, an amendment, an order | It changes the law, and it is recorded by name | Decides the quiz match and the compass |
| 2 | **Introducing legislation** — sponsoring a bill | The most a member can do on their own initiative | Not yet used (source verified, see below) |
| 3 | **Vote on a motion that only expresses a view** — "this House regrets…" | Recorded and public, but changes nothing | Counted in the voting record; excluded from the match |
| 4 | **Proposing or signing a motion** (EDMs, prayers against statutory instruments) | Entirely the member's own choice, unwhipped — but free to do and changes no law | Shown as activity; never scored |
| 5 | **Questions and speeches** | Shows where attention goes | Counted by subject; never interpreted for stance |
| – | Office held, party manifesto, declared interests | Context about constraints and influences | Not used in any score |

The split between ranks 1 and 3 is not ours. It is mySociety's distinction
between **scoring votes** ("votes that use the powers of Parliament") and
**informative votes**, set out in
[Voting and decisions on TheyWorkForYou](https://www.theyworkforyou.com/voting-information/).
Their summary of why it matters: *"Votes cast with reluctance and votes cast
with vigour are counted exactly the same in the voting lobbies."*

## Every method, and what we do with it

### A. Recorded votes

**1. Policy scorecards — used for the quiz.**
Group divisions by subject, tag each with which way a vote counts, and score a
member by how they voted across the group. This is the TheyWorkForYou model.
The grouping and the direction are editorial judgements, so we do not make
them: we use mySociety's published policies unchanged. Of their 132 Commons
policies, the 36 with at least one scoring vote in the current parliament
become quiz statements — half the House was first elected in 2024, so an older
policy would be a question most sitting members have no record on.

**2. Voting with and against the party — used in the record.**
A party's line on a division is what most of its participating members did
(at least three taking part, more than half choosing one option). A member
who did otherwise broke with it; each instance is listed with the division.
Party means *the party at the time of the vote*, from the membership the vote
was cast under. Independents have no line. Labour/Co-operative members take
the Labour whip. Over the full record the highest rates belong to Jeremy
Corbyn, John McDonnell, Christopher Chope, Brian Leishman, Diane Abbott and
David Davis — the list anyone following Westminster would give, found from
division arithmetic alone.

**3. Free votes — flagged, not weighted.**
Where parties give no instruction a vote is the member's own, which makes it
the most informative kind for telling individuals apart. mySociety marks
policies that include one (assisted dying, for instance) and the quiz shows
the flag. We do not weight free votes more heavily: a vote changes the law by
the same amount whether or not it was whipped.

**4. Ideal-point scaling (NOMINATE, optimal classification, IRT, PCA) — used
only as a check.**
Unsupervised: no tagging at all, positions fall out of who votes with whom.
In Westminster systems the leading dimension is largely government versus
opposition rather than left versus right (Spirling & McLean 2007; Hix & Noury
2016), so a coordinate cannot be shown to a voter as an ideology. We use it to
test our compass tags instead: the first principal component of MPs' quiz
positions explains 63% of the variance and correlates 0.98 with our economic
axis; the second explains 14% and correlates 0.76 with our social axis.

**5. Turnout — used in the record, with a caveat.**
Divisions voted in, out of those the member was eligible for this term.
mySociety's tables hold a row for every eligible member in every division, so
this is a true rate. It is not a measure of diligence: ministers are routinely
excused, members are "paired" with an opponent so both can be absent, and
illness and parental leave leave gaps. mySociety do not count absences in
their own summaries for this reason; nor does the quiz.

**6. Vote similarity between two members — not yet built.**
"Votes most like X" from pairwise agreement. Straightforward from data already
held.

### B. Legislative initiative

**7. Bills sponsored — verified, not yet used.**
`bills-api.parliament.uk/api/v1/Bills?MemberId={id}` lists bills a member has
sponsored; bill detail carries `sponsors`, `currentStage` and `isAct`.
Introducing a bill is the most direct thing a backbencher can do, so this is
the first addition we would make. To feed the match, each bill would need
tying to a statement — an editorial step we would want sourced the same way
as the vote mapping.

**8. Amendments tabled — not available as data.**
Published in amendment papers (PDF), not through an API.

**9. Motions proposed and signed — shown as activity.**
Early Day Motions and prayers against statutory instruments, from mySociety's
`statements` and `signatures` tables (15,700 Commons motions since 2015;
530 of 650 sitting MPs have signed one this parliament). Unwhipped and
attributable, which is rare. Also free to do and without legal effect, and
many are congratulatory — so they are counted and never scored. Ministers do
not sign EDMs by convention; an empty count is not inactivity.

**10. Devolved equivalents — verified, not yet used.**
NI Assembly: `plenary.asmx/GetPlenaryItemsTabledByMember`, `GetMotionBill`,
`GetMotionPetitionOfConcern`. Scottish Parliament: motions and members' bills
in its open data. Senedd: Member bills and statements of opinion.

### C. Attention

**11. Questions and speeches by subject — used in the record.**
Each question or speech is assigned to the subjects whose keywords it
mentions. This is the one place a list we wrote touches a published figure.
It is categorisation — nobody disputes that "waiting lists" belongs under
health — but it is ours, and it is labelled as such in the app.

**12. Committees and cross-party groups — verified, not yet used.**
`committees-api.parliament.uk/api/Members?Members={id}` (roles, dates, chairs);
NI `members.asmx/GetAllMemberRoles`, `organisations.asmx`.

**13. Self-declared interests** (`members-api…/Members/{id}/Focus`) — a member
describing themselves. Not an action; not used.

### D. Office and association

**14. Government and opposition posts** (`…/Members/{id}/Biography`).
Explains a record rather than adding to it: ministers are bound by collective
responsibility and must vote with the government or resign.

**15. Party manifestos** — a party's position, not a person's.

**16. Registers of interests and donations** — who might influence a member,
not where they stand. Collected by the scrapers; deliberately not scored.

**17. Election results** (`…/Members/{id}/LatestElectionResult`) — context.

### E. Words

**18. Lexicon stance scoring — built, tested, abandoned** (`analysis/grade.py`).
Pro and con word lists per subject, applied to speeches. It fails in a way
that cannot be patched: members speak most about what they are campaigning
against, in that subject's own vocabulary. On real data it scored Lee Anderson
strongly pro-environment for repeatedly attacking net zero. Kept in the
repository as a record of what was tried.

**19. Trained or LLM stance classification; Wordscores, Wordfish** — better at
reading text than a lexicon, but they still infer a belief from words chosen
for an audience, and each needs a judgement about which end of a scale is
which. Not used: a vote already says what a speech only implies.

**20. Surveys of members or experts** — no public source covers individual
sitting members of all four legislatures.

## How the match is computed

For each statement, a member's votes on its scoring divisions are coded for,
against, abstained, absent or not-a-member, and

    position = (for − against) / (for + against + abstained)

giving +1 for always voting for it, −1 for always against, and no position if
they never voted. Absences are not evidence either way. Decisions taken
without a division ("agreements") are excluded because nobody individually did
anything — the one place our numbers deliberately differ from mySociety's,
who include a small number.

Your answer runs from +1 (strongly agree) to −1 (strongly disagree). On each
statement you answered and the member has a position on,

    agreement = 1 − |you − them| / 2

and the match is the average, with statements you marked as mattering a lot
counted twice. It is shown with the number of statements it rests on.

**Verification.** Our for/against/absent/abstained counts were compared with
mySociety's own published figures for every sitting MP on every statement:
all 23,217 are identical.

## The compass

Twenty-three of the 36 statements are tagged with an economic axis
(left–right) or a social one (liberal–authoritarian); thirteen are left
untagged because they are packages of several things or sit on neither axis.
The tags, with a reason for each, are in `analysis/quiz_editorial.json` — the
single file holding every editorial decision we make. The same tags place the
user and every MP, so an error in one moves everyone identically.

A compass position is where *votes* sit. An opposition MP may vote against a
tax rise they would otherwise favour, or against a bill for not going far
enough, and will be placed accordingly.

## Data sources

| What | Commons | Scottish Parliament | Senedd | NI Assembly |
|---|---|---|---|---|
| Who sits, party, area | mySociety register | mySociety register | mySociety register | mySociety register |
| Votes, with eligibility and party at the time | mySociety | mySociety | mySociety | **Glasshouse scraper** — mySociety does not parse Assembly divisions |
| Vote-to-policy mapping | mySociety (132 policies) | none published | none published | none published |
| Motions signed | mySociety | not covered | not covered | scraper could add |
| Questions, speeches | Glasshouse scraper | Glasshouse scraper | Glasshouse scraper | Glasshouse scraper |
| Registers of interests | Glasshouse scraper | Glasshouse scraper | Glasshouse scraper | Glasshouse scraper |

mySociety's vote tables are one 6.5 MB file refreshed daily, replacing several
hours of per-division requests for three of the four legislatures.

**Licences.** mySociety publish their politician data and Public Whip vote
data under CC BY 4.0. Parliamentary material is under the Open Parliament
Licence v3.0. We found **no explicit licence statement for the policy
groupings themselves** on votes.theyworkforyou.com; they are published for
reuse and credited prominently here, but mySociety should be asked before any
public launch.

## Known limits

- **The quiz is Commons-only.** No independent vote-to-policy mapping exists
  for the devolved legislatures. The honest route there is statements that
  *are* divisions — "how would you have voted on this bill?" — which needs no
  mapping, only a choice of divisions and a plain description of each.
- **Statements follow the government's programme**, because they must have
  been voted on. On most of them Labour members sit at +1 and Conservatives at
  −1. What Parliament has not voted on cannot be asked.
- **Most votes are whipped.** The median member votes with their party about
  99% of the time, so a match with an MP is largely a match with their party.
- **One MP per constituency**, so "which of my representatives is closest"
  only becomes a real question once devolved members can be matched.
- **Speech figures can be older than vote figures.** Votes refresh daily;
  questions and speeches refresh when the scrapers are run. The app shows
  both dates.
- **Postcode lookup**: Senedd constituencies cannot yet be resolved from a
  postcode, and NI Assembly seats still use pre-2024 boundaries.

## References

- mySociety, *Voting and decisions on TheyWorkForYou*; *TheyWorkForYou Votes — Help & Overview*.
- Poole, K. & Rosenthal, H. (1985). A spatial model for legislative roll call analysis. *American Journal of Political Science*.
- Spirling, A. & McLean, I. (2007). UK OC OK? Interpreting optimal classification scores for the U.K. House of Commons. *Political Analysis*.
- Hix, S. & Noury, A. (2016). Government-opposition or left-right? The institutional determinants of voting in legislatures. *Political Science Research and Methods*.
- Laver, M., Benoit, K. & Garry, J. (2003). Extracting policy positions from political texts using words as data. *American Political Science Review*.
- Slapin, J. & Proksch, S.-O. (2008). A scaling model for estimating time-series party positions from texts. *American Journal of Political Science*.
