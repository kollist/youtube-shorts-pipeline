"""
setup.py - connect your accounts from the terminal, step by step (the dashboard's Accounts tab does the same thing with buttons).

    python setup.py                   walk through every platform
    python setup.py youtube           just one: youtube | meta (Facebook + Instagram) | tiktok
    python setup.py --status          which platforms are connected right now, and what is missing

You can skip everything here and still use the app: every episode's post dialog has "Save for manual posting" (video + captions in a folder).
Keys you type are saved only in .env (git-ignored). Nothing here ever posts anything.
"""

import getpass
import secrets
import sys
import webbrowser
from pathlib import Path

import setup_guides as sg


def ask(prompt: str, default: str = "") -> str:
    try:
        return input(prompt).strip() or default
    except (EOFError, KeyboardInterrupt):
        print("\nStopped. Run `python setup.py` again any time - what you saved is kept.")
        sys.exit(0)


def status() -> None:
    from social_post import platform_status
    print("\nWhat is connected right now:")
    for p in platform_status():
        print(f"  {'connected' if p['configured'] else 'MISSING  '}  {p['label']:16s} {', '.join(p['missing'])}")


def show_steps(g: dict) -> None:
    print(f"\n=== {g['label']}   [{g['level']}, {g['time']}]\n    You need: {g['needs']}\n")
    for i, s in enumerate(g["steps"], 1):
        print(f"  {i}. {s['text']}")
        if s.get("url"):
            if ask(f"     press Enter to open the page (or type s to skip): ").lower() != "s":
                webbrowser.open(s["url"])


def collect_keys(pid: str) -> None:
    keys = sg.key_state(pid)
    if not keys:
        return
    print("\nKeys (press Enter to keep what is already saved):")
    values = {}
    for k in keys:
        prompt = f"  {k['label']}{' [saved]' if k['set'] else ''}: "
        values[k["env"]] = (getpass.getpass(prompt) if k["secret"] else ask(prompt))
    saved = sg.save_keys(pid, values)
    print("  saved:", ", ".join(saved) if saved else "(nothing new)")


def login(pid: str) -> None:
    g = sg.GUIDES[pid]
    if g["login"] == "youtube":
        path = ask("\nPath to the OAuth JSON file you downloaded (Enter to skip, e.g. ~/Downloads/client_secret_....json): ")
        if path:
            try:
                print("  saved:", sg.save_client_secret(Path(path).expanduser().read_text(encoding="utf-8")).name)
            except (OSError, ValueError) as e:
                print("  could not use that file:", e); return
        if ask("Log in to YouTube now? A browser window opens. [Y/n]: ", "y").lower() == "y":
            import google_auth
            google_auth.get_credentials()
            print("  YouTube connected.")
    elif g["login"] == "meta":
        from social_common import SocialError, env
        import social_auth
        token = getpass.getpass("\nUser token from the Graph API Explorer (Enter to skip): ").strip()
        if token:
            try:
                r = social_auth.login_meta(token, env("META_APP_ID") or "", env("META_APP_SECRET") or "", ask("Page ID (only if you manage several Pages, else Enter): ") or None)
                print(f"  connected: Page '{r['page']}'" + (" + its Instagram account" if r["instagram_user_id"] else " (no Instagram account linked to it yet)"))
            except SocialError as e:
                print("  failed:", e)
    elif g["login"] == "tiktok":
        from social_common import SocialError, env
        import social_auth
        if not (env("TIKTOK_CLIENT_KEY") and env("TIKTOK_CLIENT_SECRET") and env("TIKTOK_REDIRECT_URI")):
            print("\n  Save the TikTok key, secret and redirect address first."); return
        if ask("\nStart the TikTok login now? [Y/n]: ", "y").lower() != "y":
            return
        state = secrets.token_urlsafe(16)
        url = social_auth.tiktok_authorize_url(env("TIKTOK_CLIENT_KEY"), env("TIKTOK_REDIRECT_URI"), state)
        print("  Approve in the page that opens, then copy the FULL address you land on (the page itself may show an error - that's fine).\n  " + url)
        webbrowser.open(url)
        try:
            r = social_auth.login_tiktok(env("TIKTOK_REDIRECT_URI"), ask("  Paste the address here: "), state)
            print(f"  TikTok connected (permissions: {r['scopes']}).")
        except SocialError as e:
            print("  failed:", e)


def test(pid: str) -> None:
    from social_post import MODULES
    for name in sg.GUIDES[pid].get("covers", [pid]):
        mod = MODULES.get(name)
        if mod is None:
            continue
        try:
            print(f"  test {name}: {mod.check_connection()}")
        except Exception as e:
            print(f"  test {name}: not connected yet ({str(e)[:140]})")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--status" in sys.argv:
        status(); return
    print(__doc__.split("\n\n")[0])
    pids = args or list(sg.GUIDES)
    for pid in pids:
        if pid not in sg.GUIDES:
            sys.exit(f"Unknown platform '{pid}'. Choose from: {', '.join(sg.GUIDES)}")
    for pid in pids:
        answer = ask(f"\nSet up {sg.GUIDES[pid]['label']} now? [Y/n, or q to stop]: ", "y").lower()
        if answer == "q":
            break
        if answer in ("n", "no"):
            continue
        show_steps(sg.GUIDES[pid])
        collect_keys(pid)
        login(pid)
        test(pid)
    status()
    print("\nNo accounts? You can always use 'Save for manual posting' in the dashboard's post dialog, or: python export_posts.py <series> <episode>")


if __name__ == "__main__":
    main()
