"""
publish_legal_pages.py
TikTok's developer form (and Meta's) wants public Terms-of-Service and Privacy-Policy web addresses, and TikTok wants you to prove you own the site
(it gives you a small .txt file to put on it). This makes the pages and puts them on free GitHub Pages in one go:

    python publish_legal_pages.py --name "Foundation Tapes" --credit "Stories are adapted from the SCP Wiki (CC BY-SA 3.0)."
    python publish_legal_pages.py --name "Foundation Tapes" --verify-file ~/Downloads/tiktokAbC123.txt      # add TikTok's file, run as often as needed
    python publish_legal_pages.py --name "My Channel" --dry-run                                          # only build the pages locally, publish nothing

Needs the GitHub CLI logged in once (`brew install gh`, `gh auth login`). It creates a small PUBLIC repo called <slug> under your account that holds only
these pages - nothing from this project. The pages say the app is a personal tool and collects nothing, which is true of this app; edit the text if you
change that.
"""

import argparse
import html
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
OUT_ROOT = BASE / "legal_site"

CSS = ("body{background:#0c0c0e;color:#e6e6e0;font:17px/1.6 Georgia,serif;max-width:720px;margin:0 auto;padding:40px 20px}"
       "h1{font-family:'Courier New',monospace;letter-spacing:.04em}a{color:#7fd6dc}.nav{font-family:monospace;margin-bottom:28px}")


def page(name: str, title: str, body: str) -> str:
    n = html.escape(name)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(title)} - {n}</title><style>{CSS}</style></head><body>"
            f'<div class="nav"><a href="./">{n}</a> · <a href="terms.html">Terms</a> · <a href="privacy.html">Privacy</a></div>{body}</body></html>')


def build_pages(name: str, credit: str, contact: str, platform_note: str) -> dict[str, str]:
    n, c = html.escape(name), html.escape(credit)
    credit_p = f"<p><strong>Content.</strong> {c}</p>" if credit else ""
    terms = f"""<h1>Terms of Service - {n}</h1><p><strong>Last updated: {time.strftime('%B %Y')}</strong></p>
<p>{n} is a personal, non-commercial tool used by its owner to publish short videos to the owner's own social media accounts. It is not offered to the public and has no other users.</p>
<p><strong>1. What it does.</strong> After the owner approves a video, the tool uploads that video to the owner's own account{platform_note}. It only publishes content the owner has reviewed.</p>
{credit_p}
<p><strong>2. No warranty.</strong> The tool is provided as is. The owner is responsible for the content posted.</p>
<p><strong>3. Contact.</strong> {html.escape(contact)}</p>"""
    privacy = f"""<h1>Privacy Policy - {n}</h1><p><strong>Last updated: {time.strftime('%B %Y')}</strong></p>
<p><strong>Who uses it.</strong> Only the owner of the {n} accounts.</p>
<p><strong>What data is used.</strong> When the owner logs in, the platform gives the app a login token that lets it upload videos to that one account. The token is stored on the owner's own computer and is never sent anywhere else.</p>
<p><strong>What is not collected.</strong> The app does not collect, store, sell or share personal information about any other person, and it does not read followers, messages or viewing history.</p>
<p><strong>Deleting access.</strong> The owner can remove the app's access at any time in each platform's settings (Apps and websites / Security &amp; permissions), which also invalidates the token.</p>
<p><strong>Changes.</strong> If this policy changes, this page is updated.</p>"""
    index = (f"<h1>{n}</h1><p>A personal project that publishes short videos to its owner's own accounts. {c}</p>"
             f"<p><a href='terms.html'>Terms of Service</a> · <a href='privacy.html'>Privacy Policy</a></p>")
    return {"terms.html": page(name, "Terms of Service", terms), "privacy.html": page(name, "Privacy Policy", privacy), "index.html": page(name, name, index)}


def sh(cmd: list[str], cwd: Path | None = None, check: bool = True) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"`{' '.join(cmd)}` failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help='your channel / app name, e.g. "Foundation Tapes"')
    ap.add_argument("--repo", help="GitHub repo name (default: the name as a slug)")
    ap.add_argument("--credit", default="", help="a content/licence line shown on the pages, e.g. the SCP Wiki CC BY-SA 3.0 credit")
    ap.add_argument("--contact", default="", help="how people can reach you (default: through the account on the platform)")
    ap.add_argument("--platforms", default="TikTok, YouTube, Instagram and Facebook", help="platforms named in the Terms")
    ap.add_argument("--verify-file", action="append", default=[], help="a verification .txt file from TikTok (repeat for several)")
    ap.add_argument("--dry-run", action="store_true", help="build the pages in ./legal_site/ and stop")
    a = ap.parse_args()

    slug = a.repo or re.sub(r"[^a-z0-9]+", "-", a.name.lower()).strip("-") or "legal-pages"
    contact = a.contact or f"Questions can be sent through the {a.name} account on any of the platforms above."
    site = OUT_ROOT / slug
    site.mkdir(parents=True, exist_ok=True)
    for fname, content in build_pages(a.name, a.credit, contact, f" ({a.platforms})").items():
        (site / fname).write_text(content, encoding="utf-8")
    for vf in a.verify_file:
        src = Path(vf).expanduser()
        if not src.exists():
            sys.exit(f"Verification file not found: {src}")
        shutil.copy2(src, site / src.name)
    if a.dry_run:
        print(f"Built the pages in {site} (nothing published).")
        return

    if not shutil.which("gh"):
        sys.exit("The GitHub CLI isn't installed. Run `brew install gh` and `gh auth login`, or host the files in\n"
                 f"  {site}\non any free static host (Netlify Drop, Cloudflare Pages...) and use those addresses.")
    owner = sh(["gh", "api", "user", "--jq", ".login"])
    if not (site / ".git").exists():
        sh(["git", "init", "-q", "-b", "main"], cwd=site)
    sh(["git", "add", "-A"], cwd=site)
    sh(["git", "-c", "user.name=" + owner, "-c", "user.email=" + owner + "@users.noreply.github.com", "commit", "-q", "-m", "Legal pages", "--allow-empty"], cwd=site)
    if sh(["gh", "repo", "view", f"{owner}/{slug}", "--json", "name", "--jq", ".name"], check=False) != slug:
        print(f"Creating the public repo {owner}/{slug} (it holds only these pages)...")
        sh(["gh", "repo", "create", f"{owner}/{slug}", "--public", "--source", ".", "--remote", "origin", "--push",
            "--description", f"Terms and privacy pages for {a.name}"], cwd=site)
        sh(["gh", "api", "-X", "POST", f"repos/{owner}/{slug}/pages", "-f", "source[branch]=main", "-f", "source[path]=/"], check=False)
    else:
        if "origin" not in sh(["git", "remote"], cwd=site):
            sh(["git", "remote", "add", "origin", f"https://github.com/{owner}/{slug}.git"], cwd=site)
        sh(["git", "push", "-q", "origin", "HEAD:main", "--force"], cwd=site)
    base = f"https://{owner}.github.io/{slug}/"
    print("Waiting for GitHub Pages to publish (up to ~2 minutes)...")
    for _ in range(36):
        try:
            if urllib.request.urlopen(base + "terms.html", timeout=10).status == 200:
                break
        except Exception:
            pass
        time.sleep(5)
    else:
        print("Not live yet - GitHub can take a few minutes. The addresses below will work soon.")
    print(f"\nTerms of Service URL : {base}terms.html\nPrivacy Policy URL   : {base}privacy.html\nWebsite URL / redirect: {base}")
    for vf in a.verify_file:
        print(f"Verification file    : {base}{Path(vf).name}")


if __name__ == "__main__":
    main()
