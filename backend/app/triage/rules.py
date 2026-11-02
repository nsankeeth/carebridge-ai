"""Deterministic red-flag rules. They run before any model call and set the floor the model can only raise.

The phrase lists are a starting point for a demo and must be reviewed by a clinician before real use.
"""

import re
from dataclasses import dataclass, field

from app.models import Urgency, max_urgency
from app.triage.questions import ANSWER_FLAGS

E, U = Urgency.EMERGENCY, Urgency.URGENT
YOUNG = ("infant_lt_3m", "under_5")
ALL = ("infant_lt_3m", "under_5", "child", "adult")
FEVER = r"fever|febrile|temperature|hot to the touch"


@dataclass(frozen=True)
class RuleFlag:
    code: str
    label: str
    level: Urgency


@dataclass
class RuleResult:
    level: Urgency | None
    flags: list[RuleFlag] = field(default_factory=list)


@dataclass(frozen=True)
class _Rule:
    code: str
    label: str
    patterns: tuple[str, ...]  # every pattern must match (un-negated) for the rule to fire
    levels: dict[str, Urgency]  # age band → level; bands not listed don't fire


def _lv(level: Urgency, bands: tuple[str, ...] = ALL) -> dict[str, Urgency]:
    return {b: level for b in bands}


RULES: list[_Rule] = [
    _Rule("breathing_difficulty", "Difficulty breathing", (r"can'?t breathe|cannot breathe|(?:trouble|difficulty|hard time|struggling) (?:to )?breath(?:e|ing)|short(?:ness)? of breath|can'?t catch (?:my|his|her|their) breath|gasping|breathing (?:very )?(?:fast|hard|heavily)",), _lv(E)),
    _Rule("chest_pain", "Chest pain or pressure", (r"chest (?:pain|pressure|tightness)|crushing (?:chest )?pain|(?:pain|pressure|tightness) in (?:my|his|her|their|the) chest",), _lv(E)),
    _Rule("hard_to_wake", "Hard to wake or unresponsive", (r"hard to wake|can'?t (?:wake|be woken)|won'?t wake|unresponsive|not responding|passed out|unconscious|fainted",), _lv(E)),
    _Rule("seizure", "Seizure", (r"seizure|convuls\w*|shaking uncontrollably",), _lv(E)),
    _Rule("stroke_signs", "Possible stroke signs", (r"face (?:is )?droop\w*|drooping (?:face|on one side)|slurred speech|speech is slurred|sudden weakness|one side (?:of (?:my|his|her|their) body )?(?:is |feels )?(?:weak|numb)",), _lv(E)),
    _Rule("severe_bleeding", "Severe bleeding", (r"bleeding (?:heavily|a lot|badly)|won'?t stop bleeding|bleeding (?:that )?won'?t stop|blood everywhere|soaked (?:through )?with blood|(?:vomiting|coughing up) blood",), _lv(E)),
    _Rule("blue_lips", "Blue or grey lips or skin", (r"(?:lips|face|skin) (?:look |looks |are |is |turning |turned )?(?:blue|grey|gray)|turning blue",), _lv(E)),
    _Rule("stiff_neck_fever", "Stiff neck with fever", (r"stiff neck|neck is stiff|can'?t (?:bend|move) (?:my|his|her|their) neck", FEVER), _lv(E)),
    _Rule("non_blanching_rash", "Rash that doesn't fade under pressure", (r"rash (?:that )?(?:doesn'?t|does not|won'?t) fade|purple (?:spots|rash)|non.?blanching",), _lv(E)),
    _Rule("infant_fever", "Fever in a baby under 3 months", (FEVER,), _lv(E, ("infant_lt_3m",))),
    _Rule("severe_dehydration", "Signs of dehydration", (r"(?:hasn'?t|has not|haven'?t|have not) (?:peed|urinated|weed)|no (?:wet )?(?:diapers|nappies)|no tears|very dry mouth|sunken eyes|no urine",), {**_lv(E, YOUNG), "child": U, "adult": U}),
    _Rule("green_or_bloody_vomit", "Green or bloody vomit", (r"(?:threw up|throwing up|vomit\w*|puk\w*) (?:up )?(?:green|blood|bloody)|green (?:vomit|stuff)|bloody vomit|vomit\w* (?:is |was )?(?:green|bloody)",), _lv(E)),
    _Rule("severe_abdominal_pain", "Severe or constant abdominal pain", (r"(?:severe|terrible|worst|excruciating|constant) (?:belly|stomach|tummy|abdominal) pain|(?:belly|stomach|tummy) pain (?:is )?(?:severe|constant|unbearable)",), _lv(E)),
    _Rule("suicidal_intent", "Thoughts of self-harm or suicide", (r"kill (?:myself|himself|herself)|suicid\w*|end (?:my|his|her) life|want to die|hurt (?:myself|himself|herself)|self.?harm",), _lv(E)),
    _Rule("poisoning", "Possible poisoning or overdose", (r"(?:took|swallowed|ate|drank) (?:a |the )?(?:whole |entire |full )?(?:bottle|pack|box|packet)|overdos\w*|swallowed (?:a )?(?:battery|batteries|bleach|detergent|pod|magnet)|poison\w*",), _lv(E)),
    _Rule("child_lethargy", "Lethargy in a young child", (r"letharg\w*|floppy|listless|very (?:sleepy|drowsy)|just wants to sleep",), _lv(U, YOUNG)),
    _Rule("child_refusing_fluids", "Young child refusing fluids", (r"refus\w* (?:to )?(?:drink|any (?:water|fluids|milk|juice)|fluids|(?:to )?feed)|(?:won'?t|will not|isn'?t|is not|not) (?:drink|drinking|feeding|take (?:any )?fluids)",), _lv(U, YOUNG)),
]
RULE_CODES: list[str] = [r.code for r in RULES]
_BY_CODE = {r.code: r for r in RULES}
_NEGATORS = {"no", "not", "isn't", "wasn't", "without", "denies", "never", "isnt", "wasnt"}


def age_band(age_years: float | None) -> str:
    if age_years is None:
        return "adult"
    if age_years < 0.25:
        return "infant_lt_3m"
    if age_years < 5:
        return "under_5"
    return "child" if age_years < 18 else "adult"


def _negated(text: str, start: int) -> bool:
    before = re.findall(r"[a-z']+", text[:start])[-3:]
    return any(w in _NEGATORS for w in before)


def _matches(pattern: str, text: str) -> bool:
    return any(not _negated(text, m.start()) for m in re.finditer(pattern, text))


def evaluate(text: str, answers: dict[str, str], age_years: float | None) -> RuleResult:
    band = age_band(age_years)
    t = text.lower().replace("’", "'")
    found: dict[str, RuleFlag] = {}
    for rule in RULES:
        level = rule.levels.get(band)
        if level and all(_matches(p, t) for p in rule.patterns):
            found[rule.code] = RuleFlag(rule.code, rule.label, level)
    for (qid, option), code in ANSWER_FLAGS.items():
        rule = _BY_CODE[code]
        if answers.get(qid) == option and code not in found:
            # An explicit answer counts at any age: the question was asked because it matters here.
            level = rule.levels.get(band) or max_urgency(*rule.levels.values())
            found[code] = RuleFlag(code, rule.label, level)
    flags = list(found.values())
    return RuleResult(max_urgency(*(f.level for f in flags)), flags)
