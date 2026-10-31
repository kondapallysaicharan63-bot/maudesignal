"""Chat answer tiers: which kind of answer a typed question gets, checked in order.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Used by the website chat (``POST /v1/live/ask``) and by the connector's ``ask`` tool.

1. **canned** ($0, no model): greetings (English, Hindi and Telugu, typos included), thanks,
   goodbye, who are you, what can you do, help, "is this medical advice", where the data comes
   from, privacy, a request for medical advice, a request to call a device safe or not, and
   clearly off-topic questions. Fixed text, no FDA facts.
2. **direct** ($0, no model): a simple question with one intent (alerts, what changed, check a
   product code, recalls, one report, my devices, the AI sweep, who filed the reports, one
   510(k)) is answered by the existing deterministic tools; see ``direct.py``.
3. **cache** ($0): the same question asked again within six hours reuses the live answer
   (``answer_cache.py``).
4. **live**: everything else (open questions, comparisons, "why" questions) goes to Muse Spark.

The router is rule-based and conservative: when in doubt a question goes to tier 4, where the
claim gate still checks every sentence. Nothing here calls a model or the network.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from maudesignal.connector.guidance import edit_distance, suggest_codes

Tier = Literal["canned", "direct", "cache", "live"]

#: Badge texts shown with an answer (the web UI shows them as given).
BADGE_CANNED = "No FDA facts in this message"
BADGE_DIRECT = "Direct FDA lookup — no AI"
BADGE_CACHE = "Answered earlier today"

CANNED_INTENTS = (
    "greeting",
    "thanks",
    "bye",
    "who_are_you",
    "capabilities",
    "is_medical_advice",
    "data_source",
    "privacy",
    "medical_advice",
    "safety_judgement",
    "off_topic",
)
DIRECT_INTENTS = (
    "alerts",
    "what_changed",
    "check_code",
    "recalls",
    "report",
    "my_devices",
    "ai_sweep",
    "who_filed",
    "k510",
)

#: The four suggestion chips under a canned reply (each is itself a tier-2 question).
SUGGESTIONS: tuple[str, ...] = (
    "What changed this week?",
    "Check product code LLZ",
    "Recalls for QIH",
    "Show the AI device sweep",
)

INTRO = (
    "I'm MaudeSignal, a triage aid for quality and regulatory teams. I look up FDA "
    "adverse-event reports (MAUDE), recalls and 510(k) records for AI medical devices, and "
    "every number I show is checked against stored records first."
)
MEDICAL_REPLY = "I can't give medical advice — please ask a clinician."

_CANNED_TEXT: dict[str, tuple[str, ...]] = {
    "greeting": ("Hello!", INTRO, "Try one of the questions below, or type a product code."),
    "thanks": ("You're welcome.", "Ask another question any time, or pick one below."),
    "bye": ("Goodbye, and thanks for trying MaudeSignal.", "Come back any time."),
    "who_are_you": (
        INTRO,
        "I run on stored openFDA data, and Muse Spark helps with open questions.",
    ),
    "capabilities": (
        "I can tell you what changed this week, check a product code, list recalls, open one "
        "report, look up a 510(k) by its K-number, show who filed the reports and show the AI "
        "device sweep.",
        "Open questions go to Muse Spark, and every number in its answer is checked against "
        "stored records before you see it.",
    ),
    "is_medical_advice": (
        "No. MaudeSignal is not medical advice and nothing is filed with FDA.",
        "It shows signals from public FDA records for a person in quality or regulatory to "
        "review.",
    ),
    "data_source": (
        "The data comes from public FDA sources through openFDA: MAUDE adverse-event reports, "
        "device recalls and 510(k) records, plus a stored copy used for the demo.",
        "Each fact links to the openFDA query or record behind it.",
    ),
    "privacy": (
        "Your question is not stored: only a hash of it is kept in the audit log.",
        "Please do not type patient details; MAUDE data is already de-identified.",
    ),
    "medical_advice": (
        MEDICAL_REPLY,
        "MaudeSignal only shows public FDA records for regulatory review.",
    ),
    "safety_judgement": (
        "I don't rate devices or say whether one should be used.",
        "I can show the stored reports, recalls and 510(k) records for a product code so a "
        "person can review them.",
    ),
    "off_topic": (
        "That is outside what I can help with.",
        INTRO,
    ),
}


@dataclass(frozen=True)
class Route:
    """Where a question goes, and what the router found in it."""

    tier: Tier
    intent: str
    product_codes: tuple[str, ...] = ()
    report_id: str | None = None
    k_number: str | None = None
    #: Codes written like product codes that are not known; "did you mean" is offered.
    unclear_codes: tuple[str, ...] = ()
    suggestions: tuple[str, ...] = field(default_factory=tuple)

    @property
    def product_code(self) -> str | None:
        """The one product code named, if exactly one."""
        return self.product_codes[0] if len(self.product_codes) == 1 else None


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_SPACE = re.compile(r"\s+")


def _keep(ch: str) -> str:
    """A letter, digit or combining mark (Devanagari and Telugu vowel signs), or a space."""
    if ch in "()" or ch.isspace():
        return ch
    return ch if unicodedata.category(ch)[0] in "LNM" else " "


def normalise(text: str) -> str:
    """Lower case, NFKC, punctuation dropped (letters of any script kept), spaces collapsed.

    "Hi!!  What's new?" and "hi whats new" normalise to the same text, which is also what
    the answer cache keys on.
    """
    t = unicodedata.normalize("NFKC", text).lower()
    t = t.replace("\u2019", "'").replace("'", "")
    t = "".join(_keep(ch) for ch in t)
    return _SPACE.sub(" ", t).strip()


def _words(norm: str) -> list[str]:
    return [w for w in norm.replace("(", " ").replace(")", " ").split() if w]


def _wordset(text: str) -> frozenset[str]:
    return frozenset(text.split())


# ---------------------------------------------------------------------------
# Tier 1 lexicons
# ---------------------------------------------------------------------------

#: Greeting words (Latin script). Matched exactly, or at edit distance 1 for words of 5+ letters.
_GREET_WORDS = _wordset("""
    hi hii hiii hiiii hello helo hello hallo hullo hey heyy heyyy heya hiya yo sup howdy
    namaste namastey namaskar namaskaram namaskaaram namaskaar namasthe namskar namste
    vanakkam salaam salam hola bonjour greetings morning evening afternoon gm
    """)
#: Words that may accompany a greeting without making it a question.
_GREET_FILLER = _wordset("""
    there all everyone team maudesignal maude signal bot friend sir madam ji garu good
    how are you u r doing whats up wassup going hows it ela unnaru unnav unnavu kaise ho hain
    aap ap tum bagunnara baagunnara meeru bagunnava the day today ok okay
    """)
#: Greetings in Devanagari and Telugu script (and a few mixed spellings).
_SCRIPT_GREETINGS = (
    "नमस्ते",
    "नमस्कार",
    "कैसे हो",
    "कैसे हैं",
    "हेलो",
    "నమస్తే",
    "నమస్కారం",
    "నమస్కారము",
    "ఎలా ఉన్నారు",
    "ఎలా ఉన్నావు",
    "బాగున్నారా",
    "హలో",
)
_GREET_PHRASES = (
    "how are you",
    "how r u",
    "how are u",
    "how r you",
    "how is it going",
    "hows it going",
    "whats up",
    "good morning",
    "good afternoon",
    "good evening",
    "ela unnaru",
    "ela unnav",
    "ela unnavu",
    "kaise ho",
    "kaise hain",
    "aap kaise ho",
    "aap kaise hain",
    "meeru ela unnaru",
)
_THANKS = _wordset("""
    thanks thank thanku thankyou thankss thx tnx ty tq thnx thnks thanx cheers dhanyavad
    dhanyavaad dhanyawad shukriya dhanyavadalu dhanyavaadalu appreciate appreciated great
    awesome nice cool perfect helpful much so very lot you a ok okay got it
    """)
_THANKS_CORE = _wordset("""
    thanks thank thanku thankyou thankss thx tnx ty tq thnx thnks thanx cheers dhanyavad
    dhanyavaad dhanyawad shukriya dhanyavadalu dhanyavaadalu appreciate appreciated
    """)
_BYE = _wordset("bye byee byeee goodbye good bye cya seeya see you later ttyl tata alvida night")
_BYE_CORE = _wordset("bye byee byeee goodbye cya seeya ttyl tata alvida")

_WHO = re.compile(
    r"^(?:(?:hi|hello|hey)\s+)?(?:who|what)\s+(?:are|r)\s+(?:you|u)\b"
    r"|^(?:tell me )?about (?:you|yourself|maudesignal)$"
    r"|^what is (?:maudesignal|this(?: app| tool| site)?)$"
    r"|^(?:who|what) is maudesignal\b|^introduce yourself$|^are you (?:a )?(?:bot|human|ai)$"
)
_CAPS = re.compile(
    r"^(?:help|help me|menu|options|commands|start|get started|faq|\?)$"
    r"|^what (?:can|do) (?:you|u) (?:do|help with|answer|know)\b"
    r"|^how (?:do|can) i use (?:this|you|maudesignal)\b"
    r"|^what (?:questions )?can i ask\b|^how does (?:this|maudesignal) work$"
    r"|^what should i ask\b|^can you help(?: me)?$"
)
_IS_ADVICE = re.compile(
    r"\bis (?:this|it|that|maudesignal) (?:a )?medical advice\b"
    r"|\bare you (?:giving|a source of) medical advice\b|\bnot medical advice\b"
)
_DATA_SOURCE = re.compile(
    r"\bwhere (?:does|do|is) (?:the |this |your )?data\b|\bdata (?:come|comes) from\b"
    r"|\bwhat (?:is|are) (?:the |your )?(?:data )?sources?\b|\bwhere do you get\b"
    r"|\bwhat data do you use\b|\bhow (?:fresh|current|old) is (?:the |your )?data\b"
)
_PRIVACY = re.compile(
    r"\bprivacy\b|\bdo you (?:store|keep|save|log|record) (?:my|the)\b"
    r"|\b(?:is|are) my (?:data|questions?|messages?) (?:stored|saved|kept|private)\b"
    r"|\bgdpr\b|\bhipaa\b|\bpersonal data\b|\bwho can see my\b"
)
_MEDICAL = re.compile(
    r"\bshould (?:i|my|we) (?:take|stop|use|keep using|get|have|start|worry)\b"
    r"|\b(?:can|may) i (?:take|use|stop)\b|\bmy (?:doctor|mother|father|mom|dad|wife|husband|"
    r"child|son|daughter|baby|grandma|grandpa|patient)\b"
    r"|\bdiagnos(?:e|is) (?:me|my)\b|\bi have (?:a |an )?(?:pain|fever|cancer|symptoms?|rash|"
    r"headache|infection|tumou?r|lump)\b|\bwhat (?:dose|dosage)\b|\btreatment for (?:my|me)\b"
    r"|\bam i (?:sick|ok|okay|at risk|going to)\b|\bis my (?:scan|result|x ?ray|mri|ct)\b"
    r"|\bshould i be worried\b|\bmedical advice (?:for|about|on) (?:me|my)\b"
)
_SAFETY_JUDGEMENT = re.compile(
    r"^(?:is|are) (?:the |this |that |it |these )?[\w\s()-]{0,40}? (?:safe|unsafe|dangerous)"
    r"(?: to use)?$|\bis it safe to\b|\bcan i trust (?:this|the|it)\b|^which (?:device|one) is"
    r" (?:the )?(?:safest|best)\b"
)
_OFF_TOPIC = re.compile(
    r"\bweather\b|\bjoke\b|\brecipe\b|\bcricket\b|\bfootball\b|\bsoccer\b|\bmovie\b"
    r"|\bsong\b|\blyrics\b|\bpoem\b|\bstock price\b|\bbitcoin\b|\bcrypto\b|\bcapital of\b"
    r"|\bwho won\b|\bhoroscope\b|\bwrite (?:me )?(?:an? )?(?:essay|story|code|email)\b"
    r"|\btranslate\b|\bdate night\b|\bgirlfriend\b|\bboyfriend\b|\bpizza\b|\bipl\b"
    r"|\bbollywood\b|\btollywood\b|\bplay a game\b|\btell me a story\b"
)
#: Words that make a message about FDA device data (an off-topic word is then ignored).
_DOMAIN = re.compile(
    r"\bfda\b|\bmaude\b|\bdevices?\b|\breports?\b|\brecalls?\b|\b510 ?\(?k\)?\b|\bk\d{6}\b"
    r"|\bproduct codes?\b|\bmdr\b|\badverse\b|\binjur|\bdeaths?\b|\bmalfunction|\bsignals?\b"
    r"|\bclearance\b|\bmanufacturer\b|\bcapa\b|\bsurveillance\b"
)

# ---------------------------------------------------------------------------
# Tier 2 lexicons
# ---------------------------------------------------------------------------

#: Anything that needs reasoning or a search through narratives goes to the model.
_OPEN = re.compile(
    r"\bwhy\b|\bexplain\b|\bcompare\b|\bcomparison\b|\bversus\b|\bvs\b|\bdifference\b"
    r"|\bdiffer\b|\bsimilar\b|\bmean(?:s|ing)?\b|\btrend\b|\broot cause\b|\bcause[sd]?\b"
    r"|\bsummari[sz]e\b|\bdescribe\b|\bmention(?:s|ed|ing)?\b|\bnarratives?\b|\bpattern"
    r"|\bshould\b|\bwould\b|\bcould\b|\brisk\b|\bdeadline\b|\bcapa\b|\bliterature\b|\bpubmed\b"
    r"|\bstud(?:y|ies)\b|\bpapers?\b|\bmhra\b|\bwhat kind\b|\bwhat type\b|\bwhich problems?\b"
    r"|\bhow many\b.*\b(?:injur|death|malfunction|software|mention|describe)"
    r"|\b(?:injur(?:y|ies)|deaths?|malfunctions?)\b|\bsoftware\b|\bai related\b|\bfailures?\b"
    r"|\bdraft\b|\bwrite\b|\bplan\b|\bstrategy\b|\bimpact\b|\bif\b"
)
_ALERTS = re.compile(
    r"\balerts?\b|\bnotifications?\b|\bwhat(?:s| is) flagged\b|\bflagged\b"
    r"|\banything (?:i should|to) (?:know|watch)\b|\bwarnings?\b"
)
_WHAT_CHANGED = re.compile(
    r"\bwhat (?:has |have )?changed\b|\bwhats? new\b|\bwhat is new\b|\bany ?thing new\b"
    r"|\bthis week\b|\bchanges?\b|\blatest\b|\bupdates?\b|\bwhat happened\b|\bnews\b"
)
_RECALLS = re.compile(r"\brecall(?:s|ed)?\b")
_REPORT = re.compile(
    r"\b(?:report|mdr|record|event)(?: id| number| no| key| #)?\s*(?:#\s*)?(\d{5,12}|mw\d{7})\b"
)
_K = re.compile(r"\b(k\d{6})\b")
_K510 = re.compile(r"\b510 ?\(?k\)?|\bclearance\b|\bk ?number\b|\bk\d{6}\b")
_MY_DEVICES = re.compile(
    r"\bmy (?:devices?|device types?|products?|codes?|watch ?list)\b|\bwatch ?list\b"
    r"|\b(?:devices?|codes?) i (?:watch|follow|track)\b|\bour (?:devices?|products?)\b"
)
_SWEEP = re.compile(
    r"\b(?:ai|a i) (?:device )?sweep\b|\bsweep\b|\ball ai devices\b|\bai devices? list\b"
    r"|\bai enabled devices\b|\bacross (?:all )?ai devices\b"
)
_WHO_FILED = re.compile(
    r"\bwho (?:filed|reported|submitted|sent|files)\b|\bfiled by\b|\breported by\b"
    r"|\breport(?:ing)? sources?\b|\breporters?\b|\bnot (?:filed )?by (?:the )?manufacturer\b"
    r"|\bnon ?manufacturer\b|\buser facilit"
)
_CHECK = re.compile(
    r"\bcheck\b|\bstatus\b|\bsummary\b|\boverview\b|\btell me about\b|\bshow me\b|\bshow\b"
    r"|\blook ?up\b|\binfo\b|\babout\b|\bhow is\b|\bhows\b|\bwhat about\b"
)

#: Upper-case three-letter words that are never product codes.
_NOT_CODES = _wordset("""
    FDA MDR CFR UDI PMA CAD ICU ECG EKG MRI API PDF CSV USA AND THE ARE YOU HOW WHO WHY NEW
    ANY ALL HEY BYE THX FAQ CEO CTO QMS EUA IDE GMP ISO IEC AAMI MHRA HHS CMS NIH OK AI ML
    LOL OMG YES NOT CAN DID HAS HAD GET SET PUT RUN FOR WAS ONE TWO SIX TEN OUR HER HIS ITS
    WHAT DOC
    """)
#: Lower-case English words that happen to be product codes: never read as codes unless
#: written in capitals.
_ENGLISH = _wordset("""
    max joy pre sat she pos sig oxo olo the and for you are any how who why new all hey bye
    can did has had get set put run was one two six ten our her his its yes not see say ask
    """)
_CODE_TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{3})(?![A-Za-z0-9])")


def _codes_in(text: str, known: frozenset[str]) -> tuple[list[str], list[str]]:
    """``(known_codes, unclear_codes)`` named in ``text`` (in order, no repeats).

    A capitalised three-letter word is a product code candidate; a lower-case one only when it
    is a known code and not an English word ("llz" counts, "max" does not).
    """
    found: list[str] = []
    unclear: list[str] = []
    for m in _CODE_TOKEN.finditer(text):
        raw = m.group(1)
        up = raw.upper()
        if up in _NOT_CODES:
            continue
        if raw.isupper():
            (found if up in known else unclear).append(up)
        elif up in known and raw.lower() not in _ENGLISH:
            found.append(up)
    return list(dict.fromkeys(found)), [c for c in dict.fromkeys(unclear) if c not in found]


def _fuzzy_in(word: str, lexicon: Iterable[str]) -> bool:
    if word in lexicon:
        return True
    if len(word) < 5:
        return False
    return any(len(w) >= 5 and edit_distance(word, w) <= 1 for w in lexicon)


def _only(words: list[str], core: frozenset[str], allowed: frozenset[str]) -> bool:
    """True when the words hold at least one ``core`` word and nothing outside ``allowed``."""
    if not words:
        return False
    has_core = any(_fuzzy_in(w, core) for w in words)
    return has_core and all(w in allowed or _fuzzy_in(w, core) for w in words)


def _is_greeting(norm: str) -> bool:
    raw = norm.strip()
    if any(g in raw for g in _SCRIPT_GREETINGS) and len(raw) <= 40:
        return True
    text = raw
    for phrase in _GREET_PHRASES:
        text = re.sub(rf"\b{re.escape(phrase)}\b", " greet ", text)
    words = _words(text)
    if not words:
        return False
    allowed = _GREET_WORDS | _GREET_FILLER | {"greet"}
    has_core = any(w == "greet" or _fuzzy_in(w, _GREET_WORDS) for w in words)
    if not has_core or len(words) > 8:
        return False
    return all(w in allowed or _fuzzy_in(w, _GREET_WORDS) for w in words)


def _strip_greeting(norm: str) -> str:
    """Drop a leading greeting ("hi", "hello there", "namaste,") from a longer question."""
    words = _words(norm)
    i = 0
    while (
        i < len(words)
        and i < 3
        and (_fuzzy_in(words[i], _GREET_WORDS) or (i > 0 and words[i] in ("there", "team", "all")))
    ):
        i += 1
    return " ".join(words[i:]) if 0 < i < len(words) else norm


def canned_intent(norm: str) -> str | None:
    """The tier-1 intent of a normalised message, or None."""
    if not norm:
        return "capabilities"
    if _is_greeting(norm):
        return "greeting"
    words = _words(norm)
    if _only(words, _THANKS_CORE, _THANKS | _GREET_FILLER):
        return "thanks"
    if _only(words, _BYE_CORE, _BYE | _THANKS | _GREET_FILLER):
        return "bye"
    if _MEDICAL.search(norm):
        return "medical_advice"
    if _IS_ADVICE.search(norm):
        return "is_medical_advice"
    if _WHO.search(norm):
        return "who_are_you"
    if _CAPS.search(norm):
        return "capabilities"
    if _PRIVACY.search(norm):
        return "privacy"
    if _DATA_SOURCE.search(norm):
        return "data_source"
    if _SAFETY_JUDGEMENT.search(norm):
        return "safety_judgement"
    if _OFF_TOPIC.search(norm) and not _DOMAIN.search(norm):
        return "off_topic"
    return None


def _direct_intent(
    norm: str, codes: list[str], unclear: list[str], report: str | None, k: str | None
) -> str | None:
    """The tier-2 intent of a normalised question (None: not a simple lookup)."""
    words = _words(norm)
    if len(words) > 14 or _OPEN.search(norm) or len(codes) + len(unclear) > 1:
        return None
    if k and _K510.search(norm):
        return "k510"
    if k and len(words) <= 3:
        return "k510"
    if report:
        return "report"
    if _WHO_FILED.search(norm):
        return "who_filed"
    if _RECALLS.search(norm):
        return "recalls"
    if _SWEEP.search(norm):
        return "ai_sweep"
    if _MY_DEVICES.search(norm):
        return "my_devices"
    if _ALERTS.search(norm):
        return "alerts"
    if _WHAT_CHANGED.search(norm):
        return "what_changed"
    named = codes or unclear
    if named and (_CHECK.search(norm) or len(words) <= 3 or re.search(r"\bcodes?\b", norm)):
        return "check_code"
    return None


def route(
    question: str,
    known_codes: Iterable[str],
    product_code: str | None = None,
    *,
    has_history: bool = False,
) -> Route:
    """Decide the tier of one typed question.

    Args:
        question: What the person typed.
        known_codes: Product codes the connector has a sign of (``known_product_codes``).
        product_code: The device type chosen in the page, used when the question names none.
        has_history: Earlier turns were sent: a follow-up that names no subject ("which were
            not filed by the manufacturer?") needs them, so it goes to Muse Spark.

    Returns:
        The route. ``tier`` is ``canned``, ``direct`` or ``live`` (the cache is checked by the
        caller, after this, for questions routed ``live``).
    """
    known = frozenset(c.upper() for c in known_codes)
    norm = normalise(question)
    intent = canned_intent(norm)
    if intent is not None:
        return Route("canned", intent, suggestions=SUGGESTIONS)
    rest = _strip_greeting(norm)
    if rest != norm:
        intent = canned_intent(rest)
        if intent is not None and intent != "greeting":
            return Route("canned", intent, suggestions=SUGGESTIONS)
    original = unicodedata.normalize("NFKC", question)
    codes, unclear = _codes_in(original, known)
    if not codes and not unclear and product_code and len(product_code) == 3:
        chosen = product_code.upper()
        (codes if chosen in known else unclear).append(chosen)
    k_m = _K.search(rest)
    k = k_m.group(1).upper() if k_m else None
    r_m = _REPORT.search(rest)
    report = r_m.group(1).upper() if r_m else None
    direct = _direct_intent(rest, codes, unclear, report, k)
    named = bool(codes or unclear or report or k)
    follow_up = not named and (
        _CONTEXT.search(rest) is not None or (has_history and direct in _NEEDS_SUBJECT)
    )
    if direct is None or follow_up:
        return Route("live", "open_question", tuple(codes), report, k, tuple(unclear))
    if unclear and not codes and direct not in ("report", "k510", "my_devices", "ai_sweep"):
        close = tuple(c for u in unclear for c in suggest_codes(u, known))
        if close:
            return Route(
                "direct",
                "did_you_mean",
                (),
                None,
                None,
                tuple(unclear),
                tuple(dict.fromkeys(_reask(direct, c) for c in close)),
            )
    return Route("direct", direct, tuple(codes), report, k, tuple(unclear))


#: Direct intents that need a product code; asked after earlier turns, they are follow-ups.
_NEEDS_SUBJECT = frozenset({"recalls", "who_filed", "check_code", "report", "k510"})


def _reask(intent: str, code: str) -> str:
    """The question to suggest when ``code`` is meant (a chip; never applied by itself)."""
    if intent == "recalls":
        return f"Recalls for {code}"
    if intent == "who_filed":
        return f"Who filed {code} reports?"
    if intent in ("what_changed", "alerts"):
        return f"What changed this week for {code}?"
    return f"Check product code {code}"


def canned_sentences(intent: str) -> tuple[str, ...]:
    """The fixed sentences of a canned reply."""
    return _CANNED_TEXT[intent]


_CONTEXT = re.compile(
    r"\b(?:it|its|that|those|these|them|they|this one|same|above|previous|earlier|again"
    r"|else|more|other|another)\b"
)


def cacheable(question: str, r: Route, *, has_history: bool) -> bool:
    """True when the answer to ``question`` does not depend on the earlier turns.

    A question that names its subject (a product code, a report id or a K-number), or that
    has no word pointing back ("it", "that", "those", ...), means the same thing whoever asks
    it, so its answer may be reused.
    """
    if not has_history:
        return True
    if r.product_codes or r.report_id or r.k_number:
        return True
    return _CONTEXT.search(normalise(question)) is None
