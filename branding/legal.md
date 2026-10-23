# Pages for the TikTok developer form

Put each section on its own public web page (Notion public page, published Google Doc, GitHub Pages...) and paste the links into the form.

---

## Terms of Service - Foundation Tapes

**Last updated: October 2026**

Foundation Tapes is a personal, non-commercial tool used by its owner to publish short videos to the owner's own TikTok account. It is not offered to the public and has no other users.

1. **What it does.** After the owner approves a video, the tool uploads that video to the owner's own TikTok account through TikTok's Content Posting API. It only publishes content the owner has reviewed.
2. **Content.** Stories are adapted from the SCP Wiki (scp-wiki.wikidot.com), which is licensed CC BY-SA 3.0. The original author is credited in each post. This is a fan project and is not affiliated with the SCP Wiki or its staff.
3. **No warranty.** The tool is provided as is. The owner is responsible for the content posted.
4. **Contact.** Questions can be sent through the Foundation Tapes account on TikTok.

---

## Privacy Policy - Foundation Tapes

**Last updated: October 2026**

- **Who uses it.** Only the owner of the Foundation Tapes TikTok account.
- **What data is used.** When the owner logs in, TikTok gives the app a login token that lets it upload videos to that one account. The token is stored on the owner's own computer and is never sent anywhere else.
- **What is not collected.** The app does not collect, store, sell or share personal information about any other person, and it does not read followers, messages or viewing history.
- **Deleting access.** The owner can remove the app's access at any time in TikTok under Settings -> Security & permissions -> Apps and websites, which also deletes the token.
- **Changes.** If this policy changes, this page is updated.

---

## Text for the "Explain how each product and scope works" box (for when you submit the app, max 1000 characters)

Foundation Tapes is a personal tool that publishes the owner's own short horror videos to the owner's own TikTok account. Login Kit: the owner logs in once so the app can act on that one account (scope user.info.basic shows the account name in the app so the owner can confirm which account is connected). Content Posting API, Direct Post (scope video.publish): after the owner reviews a finished video and presses Post, the app uploads that video with the owner's caption and the AI-generated-content label turned on, and the owner chooses the privacy level shown by the creator_info query. Upload to inbox (scope video.upload) is used as a fallback so the owner can finish the post inside TikTok. The app never posts without the owner pressing a button, never reads other users' data, and stores the login token only on the owner's computer.
