# How Glasshouse assesses a representative

Glasshouse answers two questions about each sitting MP, MSP, MS and MLA:

1. **What did they do?** — a factual record: turnout, breaks with their party,
   what they spend their time on.
2. **How closely do their votes match your views?** — a quiz and a match
   percentage for each parliament you are represented in, and for the House
   of Commons a compass position.

It answers the first for people who no longer sit, and for the House of Lords
(section F). It lists candidates in elections that have not happened yet, and
assesses none of them, because standing is not an act in office.

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
| 3 | **Vote on a motion that only expresses a view** — "this House regrets…" | Recorded and public, but changes nothing | Counted in the voting record; excluded from the Commons match; asked about in the devolved quizzes, and marked as a motion (method 1b) |
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

**1. Policy scorecards — used for the House of Commons quiz.**
Group divisions by subject, tag each with which way a vote counts, and score a
member by how they voted across the group. This is the TheyWorkForYou model.
The grouping and the direction are editorial judgements, so we do not make
them: we use mySociety's published policies unchanged. Of their 132 Commons
policies, 131 are asked, in two parts. The one left out, the 2010 Coalition
Programme, bundles 58 votes on unrelated measures that nobody can agree or
disagree with as one thing; the exclusion and its reason are recorded in
`analysis/quiz_editorial.json`.

- the **36 with a scoring vote in the current parliament** are asked first.
  Half the House was first elected in 2024, so these are the questions every
  sitting MP could have voted on;
- the other **95, last voted on in earlier parliaments** — tuition fees, the
  Iraq war, identity cards, same-sex marriage — are offered as a second part.
  They sharpen a visitor's place on the compass and bring in longer records
  and former MPs. An MP elected since has no position on them and is not
  marked down for it (see *How the match is computed*).

**1b. Single divisions as questions — used for the devolved quizzes.**
Nobody publishes policy groupings for the Scottish Parliament, the Senedd or
the Northern Ireland Assembly, and we will not write our own. So their
questions involve no grouping at all: each is one division, and the visitor
says how they would have voted. Aye is for, No is against; the wording is the
legislature's own title and, where its records give it, the motion as it was
put. What is left to decide is which divisions to ask about, and that is a
rule (`qualifies` in `analysis/devolved.py`), not a choice of subjects:

- a vote on a whole motion, or on a bill at a stage that decides the bill as
  a whole. Amendments, single clauses and procedural business are left out:
  an amendment cannot be understood without the thing it amends, and
  procedure is not a view on anything;
- at least one in ten of those voting on the losing side. A vote everyone
  agreed on tells you nothing about which member is closer to you;
- one question per title: a bill voted on at several stages is asked about
  once, at its most recent;
- the most recent 30 from the current term. Only when a new term has fewer
  than 20 does the list reach back into the term before, newest first.

At the last build that gave 30 questions for the Assembly (all from this
term; motion text for 21), 20 for the Scottish Parliament (4 from the term
that began in May 2026) and 20 for the Senedd (10 from this term; its record
gives titles but not motion text).

Two things make this weaker evidence than method 1, and the apps say both.
One division is one data point, where a Commons statement pools several. And
most of these divisions are on motions that express a view (rank 3 above),
because the devolved legislatures divide on few bills: 21 of the Assembly's
30, 16 of Holyrood's 20, 17 of the Senedd's 20. Leaving those out, as the
Commons quiz does, would leave too little to ask. Each question is marked
Bill or Motion.

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
test our compass tags instead. Among sitting MPs on this parliament's 36
statements, the first principal component of their positions explains 62.5%
of the variance and correlates 0.98 with our economic axis; the second
explains 14.4% and correlates 0.76 with our social axis. Across all 131
statements and all 1,472 people with a position on enough of them, the first
explains 46.0% and correlates 0.89 with the economic axis; the second explains
15.4% and correlates only 0.40 with the social one. Over nearly thirty years
what divides MPs on social questions has changed more than one axis can
follow, so the up-and-down position is rougher than the left-and-right one,
and the apps say so.

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

### F. People who are not sitting representatives

**21. Former members and the House of Lords — the same record, found by name.**
Everyone who has voted in the Commons, the Scottish Parliament or the Senedd
and no longer sits there (1,258 former MPs, 164 former MSPs, 57 former MSs),
and the 815 sitting peers, from the same mySociety tables. Each gets the
factual record of method 2; nothing is added from what they have said or done
since. A former MP has positions on the Commons statements they voted on and
can be matched against a visitor's answers. Peers cannot: there are no policy
groupings for the Lords, and nobody votes for a peer. Crossbenchers, bishops
and non-affiliated peers sit in a group with no whip, so voting unlike the
rest of the group is described as that and not as breaking with a party. A
former MP's figures are not set against today's chamber medians. Former MLAs
are not included: mySociety does not parse Assembly divisions, and our own
collection covers the current term.

**22. Candidates — listed, never assessed.**
Elections that have not happened yet, and who is standing, from Democracy
Club's Every Election and candidate registers (CC BY 4.0). A candidate has
done nothing in office, so there is nothing to score, and the apps say so on
every ballot. One who has held a seat before links to that record, by the
TheyWorkForYou id Democracy Club holds. Only what is on the ballot paper is
kept: name, party and where they are standing. The register also carries
email addresses, dates of birth and social-media accounts; none is read, and
a test (`tests/test_published_data.py`) fails if any other field appears.
Nobody is listed until they are on that register. Ballots are found for a
postcode by the official codes of the areas it falls in.

**23. Councillors — a trial, and what it found.**
There is no national record of what councillors do; each council publishes
its own. `analysis/councils.py` reads the commonest committee system
(ModernGov) for two councils. Findings, November 2026:

- **Named votes are not there to collect.** Belfast's system answers "no
  voting information available" for every councillor. Most council votes are
  a show of hands recorded only as carried or lost. A councillor therefore
  cannot be matched with anyone's views from their record, and is not.
- **Attendance is there for some.** Belfast publishes it for all 60
  councillors (median 95% of expected meetings over twelve months, lowest
  19%). It is shown as published, with what it covers. Cardiff's pages
  return nothing to an automated reader, so its 79 councillors are listed by
  name and party only.
- **Most councils refuse automated requests.** Of six others tried, four did.

So coverage of councils cannot be extended by writing more code alone.

## How the match is computed

For each statement, a member's votes on its scoring divisions are coded for,
against, abstained, absent or not-a-member, and

    position = (for − against) / (for + against + abstained)

giving +1 for always voting for it, −1 for always against, and no position if
they never voted. Every scoring vote on a policy counts, including those from
earlier parliaments — so a long-serving member's position rests on more votes
than a new member's, and the app shows the number beside each one. Absences
are not evidence either way. Decisions taken without a division
("agreements") are excluded because nobody individually did anything — the
one place our numbers deliberately differ from mySociety's, who include a
small number. A devolved question is one division, so a member's position on
it is simply +1 (aye), −1 (no), 0 (abstained) or none.

Your answer runs from +1 (strongly agree) to −1 (strongly disagree). On each
statement you answered and the member has a position on,

    agreement = 1 − |you − them| / 2

and the match is the average, with statements you marked as mattering a lot
counted twice. Each parliament is matched on its own questions; figures from
different parliaments are answers to different questions and are never
combined or compared.

Two tests decide what is done with a match (`analysis/quizmath.py`, which the
website and the phone app are both held to):

- it is **shown** when it rests on at least five statements in common (or all
  you answered, if fewer), always with that number beside it;
- it is **ranked** among "who voted most like you", and counted in a party's
  average, when it also rests on at least half of the statements you answered
  *that the member could have voted on* — those with at least one division
  held while they were a member.

The second test is about fairness between members. Someone elected in 2024
could not have voted on tuition fees in 2004; that is not a gap and does not
count against them. Someone who was a member and did not vote has left one.
For a visitor who answers all 36 of this parliament's statements, ten sitting
MPs have a figure that is shown but not ranked: the Speaker and three Deputy
Speakers, who do not vote now but voted on some of the same policies in
earlier parliaments; four MPs from Northern Ireland and Scotland; and two
others. (The seven Sinn Féin MPs, who do not take their seats, have no figure
at all.) Their constituents still see the figure and what it rests on, marked
as a partial picture. It does not sit in a ranking above members with a full
record, where five agreements would beat thirty. Before this distinction was
made, a constituent of one of those ten who answered most of the quiz was
shown no figure for their own MP.

**Verification.** When the quiz was first built, our for/against/absent/
abstained counts were compared with mySociety's own published figures for
every sitting MP on every current-parliament statement: all 23,217 were
identical. The earlier-parliament statements are produced by the same code
but have not been through that comparison. The arithmetic itself is checked
continuously: a frozen slice of real data and the reference results
(`mobile/test/fixtures/quiz_slice.json`) must be reproduced by the phone
app's tests, and the website's figures were compared with the same reference
in a browser.

## The compass

Of the 131 Commons statements, 66 are tagged: 43 with an economic axis
(left–right) and 23 with a social one (liberal–authoritarian). The other 65
are left untagged because they are packages of several things or sit on
neither axis; two that looked taggable were untagged after the votes
contradicted the tag (tax avoidance and gambling, with the measured
correlations recorded beside them). The tags, with a reason for each, are in
`analysis/quiz_editorial.json` — the single file holding every editorial
decision we make. The same tags place the user and every MP, so an error in
one moves everyone identically. The devolved questions carry no tags and
there is no compass for the devolved legislatures.

A compass position is where *votes* sit. An opposition MP may vote against a
tax rise they would otherwise favour, or against a bill for not going far
enough, and will be placed accordingly.

## Data sources

| What | Commons | Scottish Parliament | Senedd | NI Assembly |
|---|---|---|---|---|
| Who sits, party, area | mySociety register | mySociety register | mySociety register | mySociety register |
| Votes, with eligibility and party at the time | mySociety | mySociety | mySociety | **Glasshouse scraper** — mySociety does not parse Assembly divisions |
| Vote-to-policy mapping | mySociety (132 policies) | none published: single divisions asked instead | none published: single divisions | none published: single divisions |
| Motion wording for those divisions | — | mySociety's per-division record | titles only | NI Assembly Open Data |
| Motions signed | mySociety | not covered | not covered | scraper could add |
| Questions, speeches | Glasshouse scraper | Glasshouse scraper | Glasshouse scraper | Glasshouse scraper |
| Registers of interests | Glasshouse scraper | Glasshouse scraper | Glasshouse scraper | Glasshouse scraper |

mySociety's vote tables are one 6.5 MB file refreshed daily, replacing several
hours of per-division requests for three of the four legislatures. The same
tables and register cover the House of Lords and everyone who used to sit.

| What | Source |
|---|---|
| Upcoming elections, by area code | Democracy Club, Every Election (CC BY 4.0) |
| Candidates: name, party, ballot | Democracy Club candidates register (CC BY 4.0) |
| Which areas a postcode is in | postcodes.io, queried from the visitor's device |
| Councillors, wards, attendance | Each council's own ModernGov system |
| Which wards make up a Northern Ireland electoral area | District Electoral Areas (Northern Ireland) Order 2014, legislation.gov.uk (OGL v3.0) |

**Licences.** mySociety publish their politician data and Public Whip vote
data under CC BY 4.0. Parliamentary material is under the Open Parliament
Licence v3.0. We found **no explicit licence statement for the policy
groupings themselves** on votes.theyworkforyou.com; they are published for
reuse and credited prominently here, but mySociety should be asked before any
public launch.

## Known limits

- **Devolved matches rest on single votes, mostly on motions.** See method
  1b. They are a thinner and different kind of evidence from the Commons
  match, and the two are never compared.
- **New parliaments start thin.** Holyrood and the Senedd were elected in May
  2026. Most of their questions come from the term before, and a member first
  elected in 2026 did not vote on those: 65 of 129 MSPs cannot yet be matched
  on five votes.
- **The Senedd's record gives a vote's title, not its wording.** A title can
  be read either way; each question links to the record.
- **Statements follow the government's programme**, because they must have
  been voted on. On most of them Labour members sit at +1 and Conservatives at
  −1. What Parliament has not voted on cannot be asked.
- **Most votes are whipped.** The median member votes with their party about
  99% of the time, so a match with an MP is largely a match with their party.
- **One MP per constituency**, so "which of my representatives is closest"
  is a real question only where a devolved legislature adds members, and then
  only within that legislature.
- **Candidates and councillors are not assessed** (methods 22 and 23), and
  mayors, police and crime commissioners and the London Assembly appear only
  as candidates when an election is coming.
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
