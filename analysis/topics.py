"""Policy categories + Pro/Con word lexicons, and a general tone lexicon.

THIS FILE IS MEANT TO BE EDITED. The category set is based on the House of
Commons Library research-briefing topics; the Pro/Con word lists are STARTER
lists you should curate to match how you want representatives graded.

For each category:
  - keywords : words/phrases that mark a statement as being ABOUT this topic.
  - pro      : language that leans SUPPORTIVE on this topic (see the axis note
               in each category — usually "invest / protect / expand / support").
  - con      : language that leans OPPOSED / critical / restrictive.

Scoring is presence/frequency based, so:
  - single words match whole tokens ("nhs", "tax");
  - two-word phrases match adjacent tokens ("net zero", "social care").
Everything is lower-cased before matching, so write terms in lower case.

A statement's stance on a topic = (pro hits - con hits). A representative's
topic stance = sum across all their statements + their voting record on
divisions mapped to that topic. The pro/con axis is inherently a political
judgement — edit these lists so the axis means what you intend.
"""

# ---------------------------------------------------------------------------
# General tone lexicon (topic-independent positivity / negativity of language).
# Used for the "tone" component only; keep these genuinely valence-bearing.
# ---------------------------------------------------------------------------
GENERAL_POSITIVE = [
    "welcome", "welcomes", "welcomed", "support", "supports", "supported",
    "praise", "commend", "commends", "excellent", "success", "successful",
    "improve", "improved", "improvement", "progress", "benefit", "benefits",
    "positive", "opportunity", "opportunities", "protect", "protects",
    "strengthen", "invest", "investment", "deliver", "delivered", "boost",
    "thank", "thanks", "proud", "achievement", "effective", "fair", "hope",
]
GENERAL_NEGATIVE = [
    "fail", "fails", "failed", "failure", "concern", "concerned", "concerns",
    "crisis", "cut", "cuts", "cutting", "damage", "damaging", "disappointing",
    "inadequate", "unacceptable", "shameful", "scandal", "broken", "worse",
    "worsen", "decline", "neglect", "neglected", "chaos", "mismanagement",
    "waste", "wasted", "danger", "dangerous", "threat", "shortage", "delay",
    "delays", "unfair", "poverty", "harm", "harmful", "risk", "risks",
]

# ---------------------------------------------------------------------------
# Policy categories. Edit freely — add categories, tune keywords and pro/con.
# ---------------------------------------------------------------------------
TOPICS = {
    # axis: pro = more NHS funding/staff/services; con = cuts/privatisation/criticism
    "Health & social care": {
        "keywords": ["nhs", "health", "healthcare", "hospital", "hospitals", "gp",
                     "gps", "doctor", "doctors", "nurse", "nurses", "patient",
                     "patients", "a&e", "ambulance", "mental health", "social care",
                     "care home", "waiting list", "waiting times", "public health"],
        "pro": ["fund the nhs", "more funding", "more nurses", "more doctors",
                "invest", "investment", "protect", "free at the point", "expand",
                "recruit", "staffing", "support carers", "waiting times down"],
        "con": ["privatise", "privatisation", "cuts", "underfunded", "understaffed",
                "waiting lists", "rationing", "postcode lottery", "closures",
                "close", "shortage", "crisis", "backlog"],
    },
    # axis: pro = build more homes / renters' rights; con = restrict / oppose building
    "Housing & planning": {
        "keywords": ["housing", "house", "houses", "homes", "homelessness",
                     "homeless", "rent", "renters", "tenant", "tenants",
                     "landlord", "mortgage", "planning", "affordable homes",
                     "social housing", "council housing", "right to buy",
                     "leasehold", "new homes", "house building", "housebuilding"],
        "pro": ["build more", "more homes", "affordable housing", "social housing",
                "renters rights", "tenant protections", "invest", "supply",
                "council homes", "cap rents", "end no fault"],
        "con": ["block", "oppose development", "greenbelt", "green belt",
                "concreting", "overdevelopment", "nimby", "unaffordable",
                "shortage", "backlog", "delays"],
    },
    # axis: pro = welcoming/rights-based; con = restrictive/control
    "Immigration & asylum": {
        "keywords": ["immigration", "immigrant", "immigrants", "migrant",
                     "migrants", "migration", "asylum", "refugee", "refugees",
                     "border", "borders", "visa", "visas", "deportation",
                     "small boats", "channel crossings", "home office"],
        "pro": ["welcome", "safe routes", "sanctuary", "rights", "contribution",
                "integration", "compassion", "family reunion", "resettlement"],
        "con": ["crackdown", "illegal", "illegal immigration", "control",
                "controls", "deport", "deportation", "stop the boats", "tougher",
                "clampdown", "abuse", "uncontrolled", "burden", "smugglers"],
    },
    # axis: pro = climate action; con = scepticism / cost-focus
    "Environment & climate": {
        "keywords": ["climate", "climate change", "net zero", "carbon",
                     "emissions", "environment", "environmental", "pollution",
                     "biodiversity", "nature", "recycling", "flooding", "sewage",
                     "renewables", "renewable", "global warming", "greenhouse"],
        "pro": ["net zero", "climate action", "renewable", "renewables", "protect",
                "green jobs", "decarbonise", "invest", "cut emissions",
                "clean energy", "restore nature", "tackle climate"],
        "con": ["too costly", "unrealistic", "burden", "red tape", "scrap",
                "delay", "war on motorists", "unaffordable", "sceptic",
                "sceptical", "hoax", "eco zealots"],
    },
    # axis: pro = renewables/energy security investment; con = high bills/oppose transition
    "Energy": {
        "keywords": ["energy", "electricity", "gas", "oil", "nuclear", "wind",
                     "solar", "energy bills", "energy prices", "fuel", "power",
                     "grid", "north sea", "fossil fuels", "fracking",
                     "energy security"],
        "pro": ["renewable", "renewables", "clean energy", "energy security",
                "invest", "insulation", "lower bills", "home grown",
                "offshore wind", "nuclear power"],
        "con": ["high bills", "blackouts", "unreliable", "expensive", "levies",
                "ban", "windfall", "shut down", "import"],
    },
    # axis: pro = investment/services; con = cuts/austerity/tax-cutting framing
    "Economy & finance": {
        "keywords": ["economy", "economic", "gdp", "growth", "recession",
                     "inflation", "cost of living", "tax", "taxes", "taxation",
                     "budget", "deficit", "borrowing", "spending", "public finances",
                     "interest rates", "wages", "national insurance", "austerity"],
        "pro": ["invest", "investment", "growth", "living wage", "support",
                "stimulus", "fair taxes", "public services", "levelling up",
                "boost", "jobs"],
        "con": ["austerity", "cuts", "tax rises", "recession", "debt", "burden",
                "unaffordable", "black hole", "waste", "stagnation", "decline"],
    },
    # axis: pro = fund schools/teachers; con = cuts/criticism
    "Education": {
        "keywords": ["education", "school", "schools", "teacher", "teachers",
                     "pupil", "pupils", "student", "students", "university",
                     "universities", "college", "colleges", "curriculum",
                     "apprenticeship", "apprenticeships", "sen", "childcare",
                     "tuition fees", "ofsted"],
        "pro": ["invest", "more teachers", "smaller classes", "free school meals",
                "funding", "childcare", "opportunity", "skills", "support pupils",
                "recruit teachers"],
        "con": ["cuts", "underfunded", "crumbling", "shortage", "overcrowded",
                "raac", "attainment gap", "failing", "unqualified"],
    },
    # axis: pro = tougher enforcement/police numbers; con = cuts/criticism of justice system
    "Crime & justice": {
        "keywords": ["crime", "police", "policing", "prison", "prisons",
                     "sentencing", "courts", "court", "justice", "offenders",
                     "antisocial", "anti-social", "knife crime", "violence",
                     "reoffending", "probation", "victims", "law and order"],
        "pro": ["more police", "tougher sentences", "protect victims", "safer",
                "crack down", "invest", "neighbourhood policing", "back the police",
                "tackle crime"],
        "con": ["cuts", "backlog", "overcrowded prisons", "reoffending",
                "soft", "let down", "failing", "underfunded", "court delays"],
    },
    # axis: pro = strong defence spending; con = cuts/scepticism
    "Defence": {
        "keywords": ["defence", "military", "armed forces", "army", "navy",
                     "raf", "nato", "troops", "veterans", "nuclear deterrent",
                     "trident", "ukraine", "armed services"],
        "pro": ["invest", "strong defence", "support our troops", "increase spending",
                "protect", "modernise", "back our veterans", "deterrent",
                "2.5%", "rearm"],
        "con": ["cuts", "reduce", "scrap", "waste", "overspend", "disarm",
                "procurement failures", "underfunded"],
    },
    # axis: pro = internationalist/aid; con = restrict aid/inward focus
    "Foreign affairs & aid": {
        "keywords": ["foreign", "diplomacy", "international", "united nations",
                     "aid", "overseas aid", "sanctions", "trade deal",
                     "human rights", "commonwealth", "gaza", "israel", "china",
                     "russia", "foreign policy"],
        "pro": ["aid", "development", "human rights", "cooperation", "allies",
                "diplomacy", "leadership", "support", "solidarity", "0.7%"],
        "con": ["cut aid", "withdraw", "isolationist", "waste", "interference",
                "reduce", "scrap"],
    },
    # axis: pro = closer EU ties; con = pro-Brexit/divergence
    "Europe & Brexit": {
        "keywords": ["brexit", "european union", " eu ", "single market",
                     "customs union", "northern ireland protocol", "windsor framework",
                     "european", "trade barriers", "rejoin", "divergence"],
        "pro": ["closer ties", "rejoin", "single market", "customs union",
                "reduce barriers", "cooperation", "align", "youth mobility"],
        "con": ["take back control", "sovereignty", "divergence", "brexit freedoms",
                "red tape from brussels", "leave means leave", "no return"],
    },
    # axis: pro = workers' rights/jobs support; con = deregulation/critical
    "Employment & work": {
        "keywords": ["employment", "jobs", "job", "unemployment", "workers",
                     "worker", "wages", "wage", "minimum wage", "trade union",
                     "trade unions", "zero hours", "workforce", "redundancies",
                     "fire and rehire", "sick pay", "labour market"],
        "pro": ["workers rights", "living wage", "job security", "protect jobs",
                "create jobs", "fair pay", "sick pay", "ban zero hours",
                "trade union", "employment rights"],
        "con": ["red tape", "deregulate", "burden on business", "job losses",
                "redundancies", "strikes", "unaffordable", "fire and rehire"],
    },
    # axis: pro = maintain/expand welfare; con = cuts/conditionality
    "Welfare & social security": {
        "keywords": ["welfare", "benefits", "universal credit", "pension",
                     "pensions", "pensioners", "disability", "pip", "child benefit",
                     "poverty", "food banks", "cost of living", "social security",
                     "carers allowance", "winter fuel"],
        "pro": ["support", "uplift", "protect", "increase", "triple lock",
                "end poverty", "safety net", "restore", "fair", "invest"],
        "con": ["cut", "cuts", "sanctions", "crackdown", "scrounger", "reform",
                "means test", "reduce", "clampdown", "cap"],
    },
    # axis: pro = invest in transport/public transport; con = cuts/criticism
    "Transport": {
        "keywords": ["transport", "rail", "railway", "railways", "train", "trains",
                     "bus", "buses", "road", "roads", "hs2", "cycling", "potholes",
                     "aviation", "fares", "public transport", "motorway"],
        "pro": ["invest", "improve", "reopen", "electrify", "cheaper fares",
                "public transport", "cycling", "upgrade", "connectivity"],
        "con": ["cuts", "delays", "cancelled", "scrap", "potholes", "fare rises",
                "overcrowded", "underfunded", "war on motorists"],
    },
    # axis: pro = support business/enterprise; con = red tape/criticism
    "Business & industry": {
        "keywords": ["business", "businesses", "industry", "manufacturing",
                     "small business", "smes", "enterprise", "high street",
                     "retail", "steel", "exports", "productivity", "entrepreneur"],
        "pro": ["support business", "cut red tape", "invest", "enterprise",
                "grow", "back business", "exports", "innovation", "jobs"],
        "con": ["burden", "over-regulation", "closures", "decline", "offshoring",
                "taxes on business", "insolvencies", "struggling"],
    },
    # axis: pro = support farmers/food standards; con = criticism of ag policy
    "Agriculture, food & rural": {
        "keywords": ["farming", "farmers", "farm", "agriculture", "rural",
                     "food", "food security", "countryside", "fishing",
                     "fisheries", "animal welfare", "land", "crops", "livestock"],
        "pro": ["support farmers", "food security", "high standards",
                "animal welfare", "invest", "protect", "fair prices",
                "rural communities"],
        "con": ["cheap imports", "undercut", "cuts", "red tape", "neglect",
                "pollution", "decline", "struggling"],
    },
    # axis: pro = advancing equality/rights; con = opposition/rollback
    "Equality & rights": {
        "keywords": ["equality", "discrimination", "human rights", "disability",
                     "race", "racism", "lgbt", "women", "gender", "disabled",
                     "inclusion", "diversity", "civil liberties"],
        "pro": ["equality", "protect rights", "inclusion", "tackle discrimination",
                "diversity", "fairness", "accessible", "empower", "represent"],
        "con": ["woke", "roll back", "erode", "culture war", "divisive",
                "undermine", "restrict"],
    },
    # axis: pro = devolution/reform; con = centralism/status quo
    "Local government & devolution": {
        "keywords": ["council", "councils", "local government", "devolution",
                     "devolved", "mayor", "local authority", "local authorities",
                     "town", "levelling up", "regional", "community", "communities"],
        "pro": ["devolve", "invest", "empower", "local control", "funding",
                "levelling up", "support communities", "regenerate"],
        "con": ["cuts", "underfunded", "centralise", "bankruptcy", "section 114",
                "neglect", "decline"],
    },
    # axis: pro = investment in science/tech; con = criticism
    "Science, technology & digital": {
        "keywords": ["science", "research", "technology", "innovation", "digital",
                     "broadband", "artificial intelligence", " ai ", "data",
                     "online safety", "cyber", "space", "startups", "r&d"],
        "pro": ["invest", "innovation", "research funding", "world leading",
                "broadband rollout", "skills", "support", "r&d", "breakthrough"],
        "con": ["underfunded", "falling behind", "cuts", "brain drain",
                "risks", "harms", "poorly regulated"],
    },
    # axis: pro = democratic reform/standards; con = criticism/erosion
    "Parliament, elections & constitution": {
        "keywords": ["parliament", "democracy", "election", "elections", "voting",
                     "electoral", "constitution", "lords reform", "standards",
                     "sleaze", "lobbying", "voter id", "referendum", "franchise"],
        "pro": ["reform", "transparency", "accountability", "strengthen democracy",
                "votes at 16", "standards", "clean up politics", "fair votes"],
        "con": ["sleaze", "cronyism", "erode", "undermine", "gerrymander",
                "corruption", "cover up", "unaccountable"],
    },
}
