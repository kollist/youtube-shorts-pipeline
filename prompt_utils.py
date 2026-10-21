"""prompt_utils.py - small helpers for picture prompts."""

import re


def clean_image_prompt(prompt: str) -> str:
    """The pictures must carry no words (the style's own rule), but models like to write 'a sign labeled ...'.
    Drops any labeled/reads/says/text/caption clause and quoted words from the picture prompt."""
    prompt = re.sub(r"\b(?:each\s+)?(?:labeled|labelled|reads|reading|says|saying|titled|marked|with the (?:word|words|text))\b[^,.;{]*", "", prompt, flags=re.I)
    prompt = re.sub(r"[\'\"‘’“”][^\'\"‘’“”]{1,40}[\'\"‘’“”]", "", prompt)
    prompt = re.sub(r"\s+,", ",", prompt)
    prompt = re.sub(r",(?:\s*,)+", ",", prompt)
    prompt = re.sub(r",\s*(?:and|or)\s*(?=\{style\}|$)", ", ", prompt)
    return re.sub(r"\s{2,}", " ", prompt).strip()
