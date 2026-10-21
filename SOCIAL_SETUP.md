# Posting to Facebook, Instagram and TikTok

YouTube works as before. Everything below is optional and off until its keys are in `.env`.
In the dashboard, the Clips tab has a **Post to** row: tick the platforms, then Upload. A platform
without keys is greyed out and shows what it's missing. `python social_post.py status` shows the same.

A clip is only deleted from disk once **every** platform you ticked has it. If one fails, the
button says "Retry (tiktok failed)" and pressing it redoes only the failed ones - never a double post.

Check any platform without posting: `python social_post.py test facebook` (or the **Test connections** button).

## Before any keys: the accounts (do these first, from your own Facebook/Instagram)
1. **Facebook Page** - facebook.com -> menu -> Pages -> Create new Page. Name, category, one-line bio, Create.
   (Posts go to the Page, not your personal profile.)
2. **Instagram professional account** - Instagram app -> Settings -> Account type and tools -> Switch to professional
   account -> Creator or Business -> pick a category.
3. **Link them** - on the Page: Settings -> Linked accounts -> Instagram -> Connect (or in Instagram: Edit profile -> Page).
4. **TikTok** - a normal TikTok account you can log in to on the web. Make it **private** for now (see TikTok notes below).

## Facebook Reels + Instagram Reels (one setup covers both)
You need: a Facebook **Page**, and for Instagram a **Professional** (Business/Creator) account linked to that Page.
1. https://developers.facebook.com -> create an app (type: Business). Copy **App ID** and **App Secret**
   (Settings > Basic) into `.env` as `META_APP_ID` / `META_APP_SECRET`.
2. Open **Graph API Explorer**, choose your app, and generate a **User token** with these permissions:
   `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`.
   Tick your Page when asked.
3. `python social_auth.py meta` (paste the token). It swaps it for a permanent Page token and writes
   `FACEBOOK_PAGE_ID`, `FACEBOOK_PAGE_ACCESS_TOKEN` and `INSTAGRAM_USER_ID` into `.env`.
- Limits: Facebook Reels 3-90 s, 30 per 24 h. Instagram 100 per 24 h.
- While your app is in development mode it should work for Pages/accounts you own; posting for other
  people's accounts needs Meta's app review.
- Instagram: tested live. The direct ("resumable") upload was rejected by Instagram for this app
  (ProcessingFailedError), so posting uses a temporary public link instead: `public_tunnel.py` starts ngrok, serves only that one
  video at a random address until Instagram has downloaded it, then closes. You need ngrok installed and logged in once
  (`brew install ngrok`, `ngrok config add-authtoken <token>`). `INSTAGRAM_UPLOAD_MODE=url|resumable|auto` in `.env` (default auto).
- If Instagram says the Page has no linked account: `python social_auth.py instagram` re-checks the link without a new token.

## TikTok
1. https://developers.tiktok.com -> create an app; add **Login Kit** and **Content Posting API**.
   Scopes: `user.info.basic`, `video.publish`, `video.upload`.
2. Copy **Client key** / **Client secret** into `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET`.
3. Register a **redirect URI** in Login Kit. It must be **https** (TikTok rejects http://localhost) - any https
   address works, it only has to match. Put the same value in `TIKTOK_REDIRECT_URI`.
4. `python social_auth.py tiktok`: approve in the browser, then paste the full address you land on
   (the page itself may show an error - the address contains the login code).
- **Until TikTok audits your app, every post is private-only and only works on a private TikTok account.** That's
  TikTok's rule. To post publicly you must pass their audit.
- Stories made with AI: pass `--aigc` to `social_post.py video` to turn on TikTok's AI-generated label.

## Posting any video file (e.g. a story)
`python social_post.py video stories/the-new-boy/the-new-boy.mp4 --title "..." --platforms tiktok,facebook,instagram --aigc`
