"""Fixed, pre-approved patient wording. Instructions about what level of care to seek come only from here.

Wording must be reviewed by a clinician before real use.
"""

from app.models import Urgency

GUIDANCE: dict[Urgency, str] = {
    Urgency.EMERGENCY: "Call 911 now. This may be an emergency. If you can't call, ask someone nearby to call for you. "
    "We are also letting your care team know.",
    Urgency.URGENT: "This needs a clinician's attention soon. We are contacting your care team now and will show you "
    "here when they respond. If things get worse at any point, call 911.",
    Urgency.SOON: "A clinician should look at this today or tomorrow. We've sent it to your care team. If things get "
    "worse, go to urgent care, or call 911 in an emergency.",
    Urgency.ROUTINE: "We've shared this with your care team, who will get back to you. If things get worse, message "
    "us again, or call 911 in an emergency.",
}

GUIDANCE_FALLBACK = (
    "We haven't been able to reach a clinician yet. Go to urgent care or an emergency department now. "
    "If things get worse, call 911."
)

EMERGENCY_STEPS: list[str] = [
    "Call 911 and describe what is happening.",
    "Stay with the person and keep your phone on.",
    "If you can, have their health card and list of medications ready.",
    "Unlock the door so responders can get in.",
]

CARE_TIPS: dict[str, str] = {
    "small_sips": "Offer small sips of an oral rehydration solution often, such as a spoonful every few minutes.",
    "rest": "Let them rest, and check on them regularly.",
    "track_urine": "Keep track of when they last peed or had a wet diaper.",
    "light_clothing": "Dress them in light clothing and keep the room at a comfortable temperature.",
    "fluids_before_food": "Don't push solid food for now; small amounts of fluid matter more.",
    "stay_with_them": "Stay with them so you notice any change.",
    "note_symptoms": "Write down when symptoms started and any changes, to share with the clinician.",
}

WORSENING_SIGNS: dict[str, str] = {
    "breathing_difficulty": "Call 911 if breathing becomes harder, noisy, or very fast.",
    "chest_pain": "Call 911 if chest pain spreads to the arm, jaw or back, or comes with sweating.",
    "hard_to_wake": "Call 911 if they can't be woken or stop responding.",
    "seizure": "Call 911 if a seizure lasts more than a few minutes or happens again.",
    "stroke_signs": "Call 911 right away; note the time symptoms started.",
    "severe_bleeding": "Call 911 if bleeding doesn't slow with firm pressure.",
    "blue_lips": "Call 911 if lips or skin look blue or grey.",
    "stiff_neck_fever": "Call 911 if they become confused, very sleepy, or develop a rash.",
    "non_blanching_rash": "Call 911 if a rash doesn't fade when you press a glass against it.",
    "infant_fever": "Call 911 if the baby is feeding poorly, hard to wake, or breathing fast.",
    "severe_dehydration": "Call 911 if there's no pee for many hours, no tears, or they seem very drowsy.",
    "green_or_bloody_vomit": "Call 911 if vomit is green or contains blood.",
    "severe_abdominal_pain": "Call 911 if belly pain becomes severe or constant, or the belly is hard to touch.",
    "suicidal_intent": "Call 911 or 988 (Suicide Crisis Helpline) now, and don't stay alone.",
    "poisoning": "Call 911, or Poison Control, and keep the container to show them.",
    "child_lethargy": "Call 911 if they become hard to wake or stop responding to you.",
    "child_refusing_fluids": "Seek care right away if they haven't peed in 8 hours or have no tears when crying.",
}
