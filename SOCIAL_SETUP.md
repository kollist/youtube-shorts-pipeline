# Connecting YouTube, Facebook, Instagram and TikTok

**You can use the app with none of this.** In the dashboard, every episode's post dialog has **Save for manual posting**: it saves the video and
one ready-to-paste caption per platform in `exports/<series>-epNN/` (or run `python export_posts.py <series> <episode>`). Upload by hand, paste, done.

To post from the app itself, each platform needs **your own developer app**. They don't allow one shared app, and this repo can't include keys
(it's public). Three ways to do the setup, same steps:

| | |
|---|---|
| Dashboard | **Accounts** tab: a card per platform with the steps, links, boxes for the keys, login and test buttons |
| Terminal | `python setup.py` (or `python setup.py youtube`, `meta`, `tiktok`; `python setup.py --status`) |
| This page | the details below |

Keys are saved only in `.env` (git-ignored); the dashboard never shows them again. A backup of the previous `.env` is kept as `.env.bak` each time you save keys.

| Platform | Effort | What you need |
|---|---|---|
| YouTube Shorts | easy, ~10 min | a Google Cloud project with an OAuth "Desktop app" client |
| Facebook + Instagram | medium, ~30 min | a Facebook Page, an Instagram Professional account linked to it, a Meta developer app (Development mode is fine for your own accounts), ngrok for Instagram |
| TikTok | hard, 30 min + approval wait | a TikTok developer app, public terms/privacy pages, a verified site |

## YouTube
1. https://console.cloud.google.com/ -> new project -> enable **YouTube Data API v3** (and **YouTube Analytics API** for the Analytics tab).
2. OAuth consent screen: External, add yourself as a **Test user**.
3. Credentials -> Create credentials -> **OAuth client ID -> Desktop app** -> download the JSON.
4. Accounts tab: paste the JSON, **Save file**, **Log in** (a browser window opens). Or save it as `client_secret.json` and run `python setup.py youtube`.

## Facebook + Instagram
1. Link your Instagram Professional account to your Facebook Page.
2. https://developers.facebook.com/apps/ -> create an app (type Business). Copy **App ID** and **App Secret** into `META_APP_ID` / `META_APP_SECRET`.
3. In the Graph API Explorer pick your app and generate a **User token** with `pages_show_list, pages_manage_posts, pages_read_engagement, instagram_basic, instagram_content_publish, business_management` (tick your Page).
4. Accounts tab -> paste the token -> **Log in** (or `python social_auth.py meta`). It's exchanged for a Page token that doesn't expire and the Page and Instagram ids are saved to `.env`.
5. Instagram only accepts a public video link, so the app uses a temporary ngrok tunnel: `brew install ngrok`, `ngrok config add-authtoken ...`.
- New accounts: post a couple a day, not dozens. Facebook rate-limits bursts.

## TikTok
1. **Terms and privacy pages** (TikTok requires public addresses): `python publish_legal_pages.py --name "Your Channel"` publishes them on free GitHub Pages
   (needs `gh auth login`) and prints the three addresses.
2. https://developers.tiktok.com/apps -> create an app. Add products **Login Kit** and **Content Posting API** (Direct Post on). Scopes: `user.info.basic`, `video.publish`, `video.upload`.
3. Fill the terms/privacy/website addresses. TikTok asks you to **verify the site** (URL properties -> URL prefix -> download the `.txt` file). Then
   `python publish_legal_pages.py --name "Your Channel" --verify-file ~/Downloads/tiktok....txt` and press Verify.
4. Login Kit -> Redirect URI = the site address **with the trailing slash**. Put the same address, the Client key and the Client secret in `.env`
   (`TIKTOK_REDIRECT_URI`, `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`) or in the Accounts tab.
5. **Get login link**, approve, copy the address you land on (it contains `?code=`; the page may show an error, that's fine) and paste it back. Or `python social_auth.py tiktok`.
- **Until TikTok approves your app, direct posts are private-only and only work on a private account.** So the daily job sends each video to your TikTok
  **inbox as a draft**: open TikTok, paste the caption (`python auto_daily.py caption` copies it) and press Post. To get public API posting, submit the app for
  review in the portal with a screen recording of the real flow (dashboard -> Post -> TikTok login -> the video arriving).
- Stories made with AI: pass `--aigc` to `social_post.py video` to turn on TikTok's AI-generated label (the dashboard does it for series episodes).

## Check it
`python setup.py --status`, or the Accounts tab's **Test** buttons, or `python social_post.py test <facebook|instagram|tiktok>`: a harmless call that shows
which account you're connected as and posts nothing.

## Posting any video file
`python social_post.py video my.mp4 --title "..." --platforms tiktok,facebook,instagram --aigc`
