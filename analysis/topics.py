"""Policy categories + Pro/Con word lexicons, and a general tone lexicon.

THIS FILE IS MEANT TO BE EDITED. The category set is based on the House of
Commons Library research-briefing topics; the Pro/Con word lists are STARTER
lists you should curate to match how you want representatives graded.

For each category:
  - keywords : words/phrases that mark a statement as being ABOUT this topic.
  - pro      : language that leans SUPPORTIVE on this topic (see the axis note
               in each category).
  - con      : language that leans OPPOSED / critical / restrictive.

Design rule that keeps the grades meaningful:
  Pro/Con terms are DISTINCTIVE, DIRECTIONAL policy phrases — not generic
  positivity. Generic words like "invest"/"support"/"good" belong in the tone
  lexicon below, NOT in a topic's pro list, because they appear in almost every
  statement and would make everyone look "pro" everything. Prefer phrases that
  only one side of the argument actually uses ("fund the nhs" vs "nhs cuts";
  "safe routes" vs "stop the boats").

Matching notes:
  - everything is lower-cased before matching;
  - a single word matches a whole token ("nhs"); a phrase matches adjacent
    tokens ("net zero"); keep phrases to <= 4 words (longer ones never match
    and cost performance).
  - stance for a topic is only counted when the statement is ABOUT that topic
    (a keyword hit), so shared words don't bleed across categories.

The pro/con axis is a political judgement — edit these lists so the axis means
what you intend for your product.
"""

# ---------------------------------------------------------------------------
# General tone lexicon (topic-independent positivity / negativity of language).
# Drives the "tone" score only — NOT topic stance.
# ---------------------------------------------------------------------------
GENERAL_POSITIVE = [
    "welcome", "welcomes", "welcomed", "praise", "commend", "commends",
    "excellent", "success", "successful", "improve", "improved", "improvement",
    "progress", "benefit", "benefits", "positive", "opportunity", "opportunities",
    "delighted", "pleased", "encouraging", "thank", "thanks", "proud", "hope",
    "achievement", "effective", "vital", "important", "grateful",
]
GENERAL_NEGATIVE = [
    "fail", "fails", "failed", "failure", "concern", "concerned", "concerns",
    "crisis", "damage", "damaging", "disappointing", "inadequate", "unacceptable",
    "shameful", "scandal", "broken", "worse", "worsen", "decline", "neglect",
    "neglected", "chaos", "mismanagement", "waste", "wasted", "dangerous",
    "threat", "shortage", "disgrace", "appalling", "betrayal",
]

# ---------------------------------------------------------------------------
# Policy categories. Edit freely — add categories, tune keywords and pro/con.
# ---------------------------------------------------------------------------
TOPICS = {
    # axis: pro = fund/expand NHS & care ; con = cuts/privatisation/criticism
    "Health & social care": {
        "keywords": ["nhs", "health", "healthcare", "hospital", "hospitals", "gp",
                     "gps", "doctor", "doctors", "nurse", "nurses", "patient",
                     "patients", "a&e", "ambulance", "mental health", "social care",
                     "care home", "waiting list", "waiting times", "public health"],
        "pro": ["fund the nhs", "nhs funding", "invest in the nhs", "more nurses",
                "more doctors", "more gps", "free at the point", "protect the nhs",
                "save the nhs", "cut waiting times", "fund social care",
                "support for carers", "more hospital beds"],
        "con": ["privatise the nhs", "nhs privatisation", "nhs cuts", "cuts to the nhs",
                "underfunded", "understaffed", "waiting lists", "rationing",
                "postcode lottery", "hospital closures", "ward closures", "a&e crisis",
                "nhs crisis", "care crisis", "backlog"],
    },
    # axis: pro = build more homes / renter protections ; con = block/oppose/criticism
    "Housing & planning": {
        "keywords": ["housing", "house", "houses", "homes", "homelessness",
                     "homeless", "rent", "renters", "tenant", "tenants",
                     "landlord", "mortgage", "planning", "affordable homes",
                     "social housing", "council housing", "right to buy",
                     "leasehold", "new homes", "house building", "housebuilding"],
        "pro": ["build more homes", "more affordable homes", "affordable housing",
                "social housing", "council homes", "renters rights", "tenants rights",
                "cap rents", "rent controls", "end no fault evictions",
                "protect renters", "more housebuilding"],
        "con": ["block development", "oppose new homes", "protect the green belt",
                "green belt", "concreting over the countryside", "overdevelopment",
                "nimby", "planning red tape", "housing crisis", "housing shortage",
                "unaffordable homes"],
    },
    # axis: pro = welcoming / rights-based ; con = restrictive / control
    "Immigration & asylum": {
        "keywords": ["immigration", "immigrant", "immigrants", "migrant",
                     "migrants", "migration", "asylum", "refugee", "refugees",
                     "border", "borders", "visa", "visas", "deportation",
                     "small boats", "channel crossings", "home office"],
        "pro": ["safe and legal routes", "safe routes", "welcome refugees",
                "refugees welcome", "offer sanctuary", "family reunion",
                "resettlement", "humane approach", "migrants contribute",
                "protect asylum seekers"],
        "con": ["illegal immigration", "stop the boats", "crack down", "crackdown",
                "deport", "deportations", "mass deportation", "secure our borders",
                "control immigration", "reduce immigration", "tougher borders",
                "uncontrolled immigration", "people smugglers", "abuse of the system"],
    },
    # axis: pro = climate action ; con = scepticism / cost-focus
    "Environment & climate": {
        "keywords": ["climate", "climate change", "net zero", "carbon",
                     "emissions", "environment", "environmental", "pollution",
                     "biodiversity", "nature", "recycling", "flooding", "sewage",
                     "renewables", "renewable", "global warming", "greenhouse"],
        "pro": ["net zero", "climate action", "tackle climate change", "cut emissions",
                "reduce emissions", "decarbonise", "renewable energy", "clean energy",
                "green jobs", "restore nature", "protect the environment",
                "climate emergency"],
        "con": ["scrap net zero", "net zero is unrealistic", "too costly",
                "unaffordable", "war on motorists", "green levies", "red tape",
                "climate alarmism", "eco zealots", "climate sceptic", "delay net zero"],
    },
    # axis: pro = renewables/security/lower bills ; con = high bills/oppose transition
    "Energy": {
        "keywords": ["energy", "electricity", "gas", "oil", "nuclear", "wind",
                     "solar", "energy bills", "energy prices", "fuel", "power",
                     "grid", "north sea", "fossil fuels", "fracking",
                     "energy security"],
        "pro": ["renewable energy", "offshore wind", "solar power", "clean energy",
                "energy security", "home grown energy", "nuclear power",
                "home insulation", "cut energy bills", "lower energy bills"],
        "con": ["high energy bills", "soaring bills", "blackouts",
                "unreliable renewables", "green levies", "ban north sea",
                "ban new oil", "expensive energy", "energy rationing"],
    },
    # axis: pro = public investment / progressive tax ; con = austerity / low-tax framing
    "Economy & finance": {
        "keywords": ["economy", "economic", "gdp", "growth", "recession",
                     "inflation", "cost of living", "tax", "taxes", "taxation",
                     "budget", "deficit", "borrowing", "spending", "public finances",
                     "interest rates", "wages", "national insurance", "austerity"],
        "pro": ["invest in public services", "public investment", "real living wage",
                "living wage", "fair taxes", "tax the wealthy", "wealth tax",
                "fiscal stimulus", "levelling up", "end austerity"],
        "con": ["austerity", "spending cuts", "tax rises", "higher taxes", "tax hikes",
                "black hole", "national debt", "reckless spending", "unfunded spending",
                "waste of taxpayers money", "balance the books"],
    },
    # axis: pro = fund/expand schools ; con = cuts/criticism
    "Education": {
        "keywords": ["education", "school", "schools", "teacher", "teachers",
                     "pupil", "pupils", "student", "students", "university",
                     "universities", "college", "colleges", "curriculum",
                     "apprenticeship", "apprenticeships", "sen", "childcare",
                     "tuition fees", "ofsted"],
        "pro": ["invest in schools", "more school funding", "more teachers",
                "smaller class sizes", "free school meals", "protect school budgets",
                "more sen funding", "support for pupils", "scrap tuition fees",
                "early years funding"],
        "con": ["school cuts", "cuts to schools", "underfunded schools",
                "teacher shortage", "crumbling schools", "raac",
                "overcrowded classrooms", "attainment gap", "failing schools"],
    },
    # axis: pro = police numbers / tough on crime + victims ; con = cuts/failure
    "Crime & justice": {
        "keywords": ["crime", "police", "policing", "prison", "prisons",
                     "sentencing", "courts", "court", "justice", "offenders",
                     "antisocial", "anti-social", "knife crime", "violence",
                     "reoffending", "probation", "victims", "law and order"],
        "pro": ["more police", "more police officers", "tougher sentences",
                "protect victims", "neighbourhood policing", "crack down on crime",
                "tackle knife crime", "back the police", "safer streets",
                "more prison places"],
        "con": ["police cuts", "fewer police", "court backlog", "overcrowded prisons",
                "soft on crime", "high reoffending", "prison crisis",
                "victims let down", "justice delayed", "cuts to policing"],
    },
    # axis: pro = strong/higher defence spending ; con = cuts/scepticism
    "Defence": {
        "keywords": ["defence", "military", "armed forces", "army", "navy",
                     "raf", "nato", "troops", "veterans", "nuclear deterrent",
                     "trident", "ukraine", "armed services"],
        "pro": ["increase defence spending", "2.5% of gdp", "3% of gdp",
                "strengthen our armed forces", "support our troops",
                "back our veterans", "nuclear deterrent", "modernise our forces",
                "rearm", "invest in defence"],
        "con": ["defence cuts", "cut the army", "cuts to defence", "scrap trident",
                "disarm", "hollowed out", "procurement waste", "underfunded forces",
                "reduce defence spending"],
    },
    # axis: pro = internationalist / aid ; con = cut aid / inward focus
    "Foreign affairs & aid": {
        "keywords": ["foreign", "diplomacy", "international", "united nations",
                     "aid", "overseas aid", "sanctions", "trade deal",
                     "human rights", "commonwealth", "gaza", "israel", "china",
                     "russia", "foreign policy"],
        "pro": ["overseas aid", "0.7%", "restore the aid budget",
                "international development", "defend human rights", "global leadership",
                "support ukraine", "humanitarian support", "strengthen alliances",
                "international cooperation"],
        "con": ["cut foreign aid", "cut the aid budget", "aid is wasted",
                "isolationism", "foreign interference", "appeasement",
                "scrap overseas aid"],
    },
    # axis: pro = closer EU ties ; con = pro-Brexit / divergence
    "Europe & Brexit": {
        "keywords": ["brexit", "european union", " eu ", "single market",
                     "customs union", "northern ireland protocol", "windsor framework",
                     "european", "trade barriers", "rejoin", "divergence"],
        "pro": ["rejoin the eu", "closer ties with europe", "rejoin the single market",
                "customs union", "reduce trade barriers", "youth mobility",
                "align with the eu", "closer to europe"],
        "con": ["take back control", "brexit freedoms", "brexit opportunities",
                "restore sovereignty", "control our own laws", "leave means leave",
                "no going back", "regulatory divergence"],
    },
    # axis: pro = workers' rights ; con = deregulation / business burden
    "Employment & work": {
        "keywords": ["employment", "jobs", "job", "unemployment", "workers",
                     "worker", "wages", "wage", "minimum wage", "trade union",
                     "trade unions", "zero hours", "workforce", "redundancies",
                     "fire and rehire", "sick pay", "labour market"],
        "pro": ["workers rights", "employment rights", "real living wage",
                "ban zero hours", "ban fire and rehire", "statutory sick pay",
                "protect jobs", "strengthen trade unions", "right to strike",
                "secure jobs"],
        "con": ["red tape on business", "burden on employers",
                "deregulate the labour market", "anti strike laws", "curb the unions",
                "job losses", "mass redundancies", "cut employment rights"],
    },
    # axis: pro = maintain/expand welfare ; con = cuts / conditionality
    "Welfare & social security": {
        "keywords": ["welfare", "benefits", "universal credit", "pension",
                     "pensions", "pensioners", "disability", "pip", "child benefit",
                     "poverty", "food banks", "cost of living", "social security",
                     "carers allowance", "winter fuel"],
        "pro": ["raise benefits", "uplift benefits", "protect the triple lock",
                "end child poverty", "strengthen the safety net",
                "universal credit uplift", "protect pensioners",
                "restore winter fuel", "fair social security"],
        "con": ["benefit cuts", "cut benefits", "benefit sanctions",
                "crack down on benefits", "benefit scroungers", "means test",
                "cap benefits", "scrap the winter fuel", "reduce welfare"],
    },
    # axis: pro = invest in (public) transport ; con = cuts/criticism
    "Transport": {
        "keywords": ["transport", "rail", "railway", "railways", "train", "trains",
                     "bus", "buses", "road", "roads", "hs2", "cycling", "potholes",
                     "aviation", "fares", "public transport", "motorway"],
        "pro": ["invest in rail", "reopen railways", "electrify the railway",
                "cheaper fares", "cap bus fares", "better public transport",
                "fix potholes", "more cycling", "upgrade our roads"],
        "con": ["rail cuts", "scrap hs2", "cancelled hs2", "fare rises",
                "cut bus services", "overcrowded trains", "cuts to transport",
                "war on motorists"],
    },
    # axis: pro = support / cut costs for business ; con = burden / decline
    "Business & industry": {
        "keywords": ["business", "businesses", "industry", "manufacturing",
                     "small business", "smes", "enterprise", "high street",
                     "retail", "steel", "exports", "productivity", "entrepreneur"],
        "pro": ["back british business", "support small businesses",
                "cut business rates", "cut business red tape", "boost exports",
                "back manufacturing", "save british steel", "support enterprise",
                "industrial strategy"],
        "con": ["burden on business", "over regulation", "business rates too high",
                "offshoring", "factory closures", "business closures", "insolvencies",
                "anti business", "taxes on business"],
    },
    # axis: pro = support farmers / food standards ; con = undercut / criticism
    "Agriculture, food & rural": {
        "keywords": ["farming", "farmers", "farm", "agriculture", "rural",
                     "food", "food security", "countryside", "fishing",
                     "fisheries", "animal welfare", "land", "crops", "livestock"],
        "pro": ["support our farmers", "back british farmers", "food security",
                "high food standards", "protect animal welfare",
                "fair prices for farmers", "protect the countryside",
                "support rural communities"],
        "con": ["cheap food imports", "undercut our farmers", "lower food standards",
                "farming cuts", "inheritance tax on farms", "chlorinated chicken",
                "neglect rural areas", "family farm tax"],
    },
    # axis: pro = advance equality/rights ; con = rollback / culture-war framing
    "Equality & rights": {
        "keywords": ["equality", "discrimination", "human rights", "disability",
                     "race", "racism", "lgbt", "women", "gender", "disabled",
                     "inclusion", "diversity", "civil liberties"],
        "pro": ["tackle discrimination", "equal rights", "protect human rights",
                "disability rights", "womens rights", "lgbt rights",
                "close the pay gap", "promote inclusion", "equal opportunities"],
        "con": ["woke", "culture war", "roll back rights", "erode rights",
                "undermine equality", "anti woke", "identity politics"],
    },
    # axis: pro = devolve / fund local ; con = cuts / centralisation
    "Local government & devolution": {
        "keywords": ["council", "councils", "local government", "devolution",
                     "devolved", "mayor", "local authority", "local authorities",
                     "town", "levelling up", "regional", "community", "communities"],
        "pro": ["devolve power", "more devolution", "empower local councils",
                "fund local government", "directly elected mayors",
                "local decision making", "back our high streets",
                "regenerate our towns"],
        "con": ["council cuts", "council bankruptcy", "section 114",
                "centralise power", "strip local powers", "underfund councils",
                "cuts to local services"],
    },
    # axis: pro = invest in / lead on science & tech ; con = cuts / harms
    "Science, technology & digital": {
        "keywords": ["science", "research", "technology", "innovation", "digital",
                     "broadband", "artificial intelligence", " ai ", "data",
                     "online safety", "cyber", "space", "startups", "r&d"],
        "pro": ["invest in research", "r&d funding", "world leading science",
                "roll out broadband", "gigabit broadband", "back innovation",
                "support startups", "science superpower", "fund research"],
        "con": ["research cuts", "brain drain", "falling behind", "cuts to science",
                "online harms", "poorly regulated ai", "underfund research"],
    },
    # axis: pro = democratic reform / standards ; con = sleaze / erosion
    "Parliament, elections & constitution": {
        "keywords": ["parliament", "democracy", "election", "elections", "voting",
                     "electoral", "constitution", "lords reform", "standards",
                     "sleaze", "lobbying", "voter id", "referendum", "franchise"],
        "pro": ["clean up politics", "greater transparency", "accountability",
                "strengthen democracy", "votes at 16", "lords reform",
                "proportional representation", "fair votes",
                "standards in public life"],
        "con": ["sleaze", "cronyism", "corruption", "cover up", "gerrymandering",
                "voter suppression", "unaccountable", "erode standards",
                "cash for access"],
    },
}
