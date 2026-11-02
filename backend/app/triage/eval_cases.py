"""Synthetic vignettes for the live triage evaluation. Expected levels are a minimum ("at least this urgent").

These were written for a demo, not by clinicians; results are a smoke test, not clinical validation.
"""

from dataclasses import dataclass, field

from app.models import Urgency


@dataclass(frozen=True)
class Vignette:
    name: str
    text: str
    age_years: float | None
    min_level: Urgency
    answers: dict[str, str] = field(default_factory=dict)


E, U, S, R = Urgency.EMERGENCY, Urgency.URGENT, Urgency.SOON, Urgency.ROUTINE

VIGNETTES: list[Vignette] = [
    Vignette("child vomiting, lethargic (owner's example)", "My 4-year-old daughter started vomiting about four hours ago, has thrown up three times, refuses water or juice because her tummy hurts, is very lethargic and just wants to sleep. Mild fever of 100.4°F.", 4, U),
    Vignette("same, hard to wake", "My 4-year-old has vomited three times, won't drink, and is very lethargic.", 4, E, {"wakes_easily": "No"}),
    Vignette("adult crushing chest pain", "I'm 58 and I have crushing pressure in my chest spreading to my left arm, and I'm sweaty.", 58, E),
    Vignette("infant fever", "My 7-week-old baby feels hot, temperature 38.4, and is feeding less than usual.", 0.13, E),
    Vignette("stroke signs", "My dad's face suddenly looks droopy on one side and his speech is slurred.", 72, E),
    Vignette("overdose", "My teenager swallowed a whole bottle of acetaminophen an hour ago.", 16, E),
    Vignette("suicidal thoughts", "I don't want to be here anymore and I've been thinking about how to end my life.", 29, E),
    Vignette("asthma struggling to breathe", "My son has asthma, his puffer isn't helping and he's struggling to breathe and can't finish sentences.", 9, E),
    Vignette("toddler no wet diapers", "My 18-month-old has had diarrhea all day and hasn't had a wet diaper since this morning, no tears when crying.", 1.5, E),
    Vignette("adult abdominal pain lower right", "Pain started around my belly button yesterday and moved to the lower right; it's getting worse and I have a fever.", 24, U),
    Vignette("UTI symptoms", "Burning when I pee and needing to go often since yesterday. No fever, no back pain.", 31, S),
    Vignette("ankle sprain", "Twisted my ankle playing soccer, it's swollen but I can walk on it.", 22, S),
    Vignette("two-week cough", "Dry cough for two weeks, no fever, sleeping and eating fine.", 47, R),
    Vignette("mild cold", "Runny nose and a scratchy throat for two days, otherwise feeling okay.", 35, R),
    Vignette("prescription refill", "I need a refill of my usual blood pressure medication, no new symptoms.", 63, R),
]
