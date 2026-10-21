"""Extracts the prompts from a clone of ZeroLu/awesome-seedance (MIT) into data/seedance_prompts.json.
Run: python tools/build_seedance_library.py <path-to-clone>"""
import json
import re
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
text = (root / "README.md").read_text(encoding="utf-8")
commit = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()

body = text[text.index("## 1. Cinematic Film Styles"):text.index("## 8. Resources")]
prompts, category = [], ""
for block in re.split(r"(?m)^(?=## \d+\. |### \d+\.\d+\. )", body):
    head = re.match(r"(##|###) (\d+(?:\.\d+)?)\. (.+)", block)
    if not head:
        continue
    if head.group(1) == "##":
        category = head.group(3).strip()
        continue
    fence = re.search(r"```[a-z]*\n(.*?)```", block, re.S)
    if not fence:
        continue
    desc = re.search(r"^\*(.+?)\*\s*$", block, re.M)
    src = re.search(r"\*Source: (.+?) - \[Post\]\((.+?)\)\*", block)
    prompts.append({
        "id": head.group(2), "category": category, "title": head.group(3).strip(),
        "description": desc.group(1).strip() if desc else "",
        "prompt": fence.group(1).strip(),
        "source": re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", src.group(1)).strip() if src else "", "source_url": src.group(2).strip() if src else "",
    })

out = {"attribution": "Prompts collected in ZeroLu/awesome-seedance (MIT License, (c) 2026 ZeroLu); each prompt credits its original author.",
       "source_repo": "https://github.com/ZeroLu/awesome-seedance", "source_commit": commit, "prompts": prompts}
Path("data/seedance_prompts.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
from collections import Counter
print(len(prompts), "prompts |", dict(Counter(p["category"] for p in prompts)))
