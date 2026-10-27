"""
story_variety.py
So a viewer who has seen five tapes cannot predict the sixth. Four layers, each rotated (least recently used first, never the same twice in a row):

  SHAPES    how the story is told   (orientation tape / incident report / survivor account / day log / safety video / cold open)
  FINALES   how the last line works (taunt / command / confession / countdown / lullaby / the narrator was it / mimic / unfinished)
  PROFILES  where and how the scare lands (classic mid-story scream / late scream / quiet dread, no scream / fake calm then scream / two scares)
  ARCHIVIST a thread across tapes: a short note on each end card from the person who keeps the tape library, creeping from bureaucratic to personal,
            and the narrator's voice degrading a little with every tape

Everything falls back to the old behaviour if anything here fails (`choose` never raises), so a bug can't cost a day of posting.
"""

import json
import random
import zlib
from pathlib import Path

DATA = Path(__file__).parent / "data"
STATE = DATA / "variety_state.json"
NOTES = DATA / "archivist_notes.json"

# ------------------------------------------------------------------ story shapes: the 8 beats (same scene kinds as always: 1 intro, 2-6 rule 1-5, 7-8 twist)
ORIENTATION = """1. HOOK + WHAT IT IS: one chilling, concrete sentence that makes people need to know more, then what the thing is, in plain words ("This is a statue. It is alive.").
2. WHAT IT DOES: its one terrifying ability or behaviour, said simply, with the consequence.
3. WHY IT IS DANGEROUS: one specific fact from the article that makes it real (where it was found, what it did, what it leaves behind).
4. HOW THE FOUNDATION KEEPS IT LOCKED UP: the containment, explained as a story.
5. HOW IT IS WATCHED: the monitoring and procedures in plain steps - who watches, how often, what they do and what happens if they slip.
6. THE MISTAKE: the one thing that goes wrong (from the article's incidents or procedures), told in second person - you are the one on watch.
7. THE TURN: the moment you realise it already happened. Quiet and cold.
8. THE SCARE: {finale}"""

INCIDENT_REPORT = """TOLD AS A CLASSIFIED INCIDENT REPORT read aloud by a flat, tired official: dated, timed entries ("At two fourteen in the morning..."), clinical words, one detail that does not belong. Second person is NOT used; "you" only appears in beat 7.
1. HOOK + WHAT IT IS: "This report was never meant to leave the archive." Then, in plain words, what the thing is.
2. WHAT HAPPENED FIRST: the first time staff noticed what it does, with a time stamp and the consequence.
3. THE CASUALTIES OR DAMAGE: one specific fact from the article that makes it real.
4. THE RESPONSE: how the Foundation locked it up afterwards, as a story.
5. THE PROCEDURE: the rules staff were given afterwards, in plain steps, and what happens if they slip.
6. WHAT THE REPORT LEAVES OUT: the one mistake or detail from the article that the official keeps trying to skip.
7. THE TURN: the official realises the last entry in the report was not written by them. Quiet and cold; "you" may appear here.
8. THE SCARE: {finale}"""

SURVIVOR = """TOLD IN THE FIRST PERSON BY A SURVIVOR recording a statement in a bare room ("I am going to tell you what happened, and I need you to listen all the way through"). Tired, quiet, honest. "I", "we", "my team".
1. HOOK + WHAT IT IS: why the speaker should not be alive, then what the thing is, in plain words.
2. WHAT IT DOES: what we learned it does, said simply.
3. WHAT IT DID TO MY TEAM: one specific fact from the article that makes it real.
4. HOW WE LOCKED IT UP: the containment, explained as something we built.
5. THE RULES WE KEPT: the procedures, in plain steps, and what happens if you slip.
6. THE MISTAKE I MADE: the one thing that went wrong, owned by the speaker.
7. WHAT I UNDERSTOOD TOO LATE: quiet and cold.
8. THE SCARE: {finale}"""

DAY_LOG = """TOLD AS A DAY-BY-DAY LOG read aloud by a researcher who is getting more tired and less careful ("Day one.", "Day two."). Each scene starts with its day. Short, plain, factual, then one detail that is wrong.
1. DAY ONE - HOOK + WHAT IT IS: the arrival, a chilling sentence, then what the thing is in plain words.
2. DAY TWO: what it does, said simply, with the consequence.
3. DAY THREE: one specific fact from the article that makes it real.
4. DAY FOUR: how it is locked up, as a story.
5. DAY FIVE: the procedures, in plain steps, and what happens if staff slip.
6. DAY SIX: the researcher makes the one mistake from the article.
7. DAY SEVEN: the entry is shorter; the researcher realises it already happened.
8. THE NEXT ENTRY: {finale}"""

SAFETY_VIDEO = """TOLD AS AN UPBEAT FOUNDATION STAFF SAFETY BRIEFING read aloud by a cheerful corporate announcer ("Welcome, and congratulations on your new posting!") whose cheer slowly drains away scene by scene. Everything is explained clearly because it is a briefing - that is what makes it horrible.
1. WELCOME + WHAT IT IS: a bright hook, then what the thing is, in plain words.
2. REMEMBER, IT DOES THIS: what it does, with the consequence, still cheerful.
3. WHY WE TAKE THIS SERIOUSLY: one specific fact from the article that makes it real; the cheer wobbles.
4. HOW WE KEEP IT SAFE: the containment, as friendly reassurance.
5. YOUR DAILY CHECKLIST: the procedures in plain steps, and what happens if you slip; the announcer is quieter.
6. THE ONE THING NOT TO DO: the mistake from the article, said flatly.
7. IF YOU ARE HEARING THIS: the announcer stops pretending. Quiet and cold.
8. THE SCARE: {finale}"""

COLD_OPEN = """STARTS AT THE END: the very first sentence is a flash-forward to the moment it gets you, then the narrator says they have to explain how you got there. Calm, serious, documentary.
1. FLASH-FORWARD + WHAT IT IS: one chilling sentence from the last moment ("In forty seconds you will stop breathing."), then "Let me explain." and what the thing is, in plain words.
2. WHAT IT DOES: its one terrifying ability, said simply, with the consequence.
3. WHY IT IS DANGEROUS: one specific fact from the article that makes it real.
4. HOW THE FOUNDATION KEEPS IT LOCKED UP: the containment, explained as a story.
5. HOW IT IS WATCHED: the monitoring and procedures in plain steps, and what happens if they slip.
6. THE MISTAKE: the thing that goes wrong, in second person - you are the one on watch.
7. THE TURN: we are back at the flash-forward; the sentence from beat 1 is happening now. Quiet and cold.
8. THE SCARE: {finale}"""

SHAPES = {"orientation": ORIENTATION, "incident_report": INCIDENT_REPORT, "survivor": SURVIVOR, "day_log": DAY_LOG, "safety_video": SAFETY_VIDEO, "cold_open": COLD_OPEN}
SHAPE_LABELS = {
    "orientation": '"WHAT IT IS", "WHAT IT DOES", "HOW IT\'S CONTAINED", "WHO WATCHES IT", "THE MISTAKE"',
    "incident_report": '"INCIDENT 1", "THE DAMAGE", "THE RESPONSE", "PROCEDURE", "NOT IN THE REPORT"',
    "survivor": '"MY STATEMENT", "WHAT IT DOES", "MY TEAM", "WHAT WE BUILT", "OUR RULES", "MY MISTAKE"',
    "day_log": '"DAY 1", "DAY 2", "DAY 3", "DAY 4", "DAY 5", "DAY 6", "DAY 7"',
    "safety_video": '"WELCOME", "REMEMBER", "WHY IT MATTERS", "STAYING SAFE", "YOUR CHECKLIST", "NEVER"',
    "cold_open": '"LATER", "WHAT IT IS", "HOW IT\'S CONTAINED", "WHO WATCHES IT", "THE MISTAKE"',
}

# ------------------------------------------------------------------ how the last spoken line works. "question" = a viewer question is shown as end-card text (spoken line stays separate)
FINALES = {
    "taunt": ("the ENTITY speaks to the viewer in FIRST PERSON, close and intimate, never the narrator describing it: it is right behind them and says so, as a taunt that fits what it does "
              "(e.g. \"Turn around. I am right here, inches from your neck. Go on... blink.\"). 12-20 words.", True),
    "command": ("the entity gives ONE calm, simple instruction that the viewer has already obeyed or is about to, such as \"Do not look away from the screen.\" or \"Stay exactly where you are.\" 8-14 words. "
                "Do NOT say it is behind you and do NOT use the words \"turn around\".", False),
    "confession": ("the narrator's voice turns out to belong to the entity, which confesses what it did, calmly and in the first person (\"I was the one who left the door open. I wanted you to find me.\"). 14-20 words. "
                   "No \"behind you\".", False),
    "countdown": ("the entity counts down slowly from five, and the line stops before it reaches zero, e.g. \"Five. Four. Three. Two.\" - nothing else, 4-8 words. No \"behind you\".", False),
    "lullaby": ("the entity softly recites a four-line nursery-style rhyme about the exact thing it does to people, short lines, simple words, quietly wrong. 16-24 words. No \"behind you\".", False),
    "narrator_is_it": ("the narrator reveals that THEY are the entity and the whole file was read to keep the viewer still and listening (\"I am not the narrator. I have been reading you this file so you would stay still.\"). 14-22 words. No \"behind you\".", False),
    "mimic": ("the entity describes the viewer's own situation right now, in the present tense, as if it can see it: where they are, the light of their screen, that they are alone, and ends calmly (\"You are alone with this. "
              "The only light in the room is your screen. I can see it from here.\"). 14-22 words. No \"behind you\".", False),
    "unfinished": ("the entity starts one short sentence and it is cut off mid-word by a dash, e.g. \"It is not in the wall. It is right beh—\". 6-12 words. Avoid repeating \"behind\" if it was in the last episode.", False),
}

# ------------------------------------------------------------------ where the scare lands (read by horror_video.py)
PROFILES = {
    "classic": "one big scream right after the first twist scene, mid-story (the original)",
    "late": "no mid-story scream: the dread builds for the whole story and the scream hits at the reveal",
    "quiet": "no scream at all: heartbeat, silence, a low hit, the whisper - the dread is the scare",
    "false_calm": "a small stab mid-story that feels like the scare, a stretch of calm, then the real scream at the reveal",
    "double": "two scares: the mid-story scream and a second one at the reveal",
}


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _pick(kind: str, options: list[str], seed: str, st: dict, remember: bool) -> str:
    hist = st.get(kind, [])
    rng = random.Random(zlib.crc32(f"{kind}|{seed}".encode()))
    recent = hist[-(len(options) // 2 or 1):]                       # avoid anything used in the last few tapes
    pool = [o for o in options if o not in recent] or [o for o in options if o != (hist[-1] if hist else None)] or options
    choice = rng.choice(pool)
    if remember:
        st[kind] = (hist + [choice])[-30:]
    return choice


def choose(seed_text: str, remember: bool = True) -> dict:
    """{"shape", "finale", "profile"} - rotated so consecutive tapes differ. Never raises: on any problem returns the original behaviour."""
    try:
        st = _state()
        out = {"shape": _pick("shape", list(SHAPES), seed_text, st, remember),
               "finale": _pick("finale", list(FINALES), seed_text, st, remember),
               "profile": _pick("profile", list(PROFILES), seed_text, st, remember)}
        if remember:
            DATA.mkdir(exist_ok=True)
            STATE.write_text(json.dumps(st), encoding="utf-8")
        return out
    except Exception:
        return {"shape": "orientation", "finale": "taunt", "profile": "classic"}


def beats(shape: str, finale: str) -> tuple[str, bool]:
    """The story-order block for the writer and whether the finale carries a viewer question."""
    text, question = FINALES.get(finale, FINALES["taunt"])
    ask = (" Then ONE final sentence: a question to the viewer (6-9 words) - it is shown as text, not spoken." if question
           else " There is NO viewer question this time: the story ends on that last line.")
    return SHAPES.get(shape, ORIENTATION).format(finale=text + ask), question


# ------------------------------------------------------------------ the archivist thread across tapes
NOTES_PROMPT = """Write 24 one-line notes that appear at the very end of a long series of horror "orientation tapes", signed by an unseen archivist who keeps the tape library. They must read as one slow story
told only through these notes, from dull paperwork to personal dread, and the reader should feel someone is changing the tapes and watching who watches them:
notes 1-4 are bureaucratic (catalogue, reviewed, filed); 5-9 something small is off (the audio does not match the log, a tape was returned rewound, a label was changed);
10-16 the archivist starts to suspect someone is rewatching them and that the narrator's voice is not always the same; 17-22 they are frightened, careful, leaving things out;
23 the notes admit a tape was watched by someone who should not exist; 24 speaks directly to the viewer in a quiet, unsettling way.
NEVER write a tape number or any digit: say "this tape", "the last tape", "tonight", "the narrator", "the library". Each note: max 58 characters, plain sentence case, no quotation marks, no numbering, no emoji, no real names. Respond with ONLY JSON: {"notes": ["...", ...24 items]}"""


def archivist_notes() -> list[str]:
    try:
        return json.loads(NOTES.read_text(encoding="utf-8"))["notes"]
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    try:
        from series import _llm_json
        notes = [str(n).strip()[:60] for n in _llm_json(NOTES_PROMPT, "Write the notes.").get("notes", []) if str(n).strip()]
        if len(notes) >= 12:
            DATA.mkdir(exist_ok=True)
            NOTES.write_text(json.dumps({"notes": notes}, indent=1), encoding="utf-8")
            return notes
    except Exception:
        pass
    return []


def archivist_note(tape_no: int) -> str:
    """'TAPE 07 - <note>' for the end card, or '' if the notes aren't available."""
    notes = archivist_notes()
    if not notes or tape_no < 1:
        return ""
    return f"TAPE {tape_no:02d}  -  {notes[min(tape_no - 1, len(notes) - 1)]}"


def narrator_damage(tape_no: int) -> float:
    """0..1: how much the narrator's voice has degraded by this tape (full effect around tape 25)."""
    return max(0.0, min(1.0, (tape_no - 1) / 24.0))
