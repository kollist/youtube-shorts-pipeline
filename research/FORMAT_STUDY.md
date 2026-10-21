# Format study - 21 Oct 2026

Method: YouTube Data API (search ordered by views, videos under 4 min, published in the last 75 days, region US, relevance language en),
11 candidate formats x 2-3 queries x 40 results = 818 videos (724 Shorts-length), with view counts and channel sizes (`yt_format_sample_2026-10-21.json`).
"Breakout" = channel <= 100k subs, video >= 100k views and >= 5x the channel's subscriber count.

Biases to remember: search returns the top-viewed results per query, so this measures each format's CEILING, not its average; the "English" filter is a rough
ASCII test (romanised Hindi slips through); no retention data; YouTube only; blogs/vendors excluded from the numbers.

| format | EN videos | EN median views | EN >=1M | EN breakouts |
|---|---|---|---|---|
| satisfying physics / marble / 3D-print simulations | 63 | 1,263,234 | 37 | 44 |
| AI animal cartoons | 51 | 673,482 | 18 | 47 |
| visual facts | 65 | 201,413 | 11 | 19 |
| 3D scale explainers | 47 | 53,612 | 9 | 9 |
| illustrated horror stories | 38 | 36,164 | 4 | 6 (non-English: 33 videos >= 1M, Hindi horror cartoons) |
| history POV | 42 | 21,546 | 1 | 5 |
| stickman | 76 | 6,359 | 4 | 10 |
| parable / moral | 42 | 1,274 | 5 | 13 (a few huge: 18.4M for an elephant-and-ants moral story) |
| unsolved mystery narrated | 64 | 1,204 | 10 | 14 |
| text-message stories | 44 | 1,423 | 0 | 2 |
| Reddit story over gameplay | 56 | 1,490 | 1 | 0 |

Breakout durations: median 28 s; 31% <= 15 s; 56% <= 30 s; 87% <= 60 s. 79 of 241 breakout channels had <= 50 videos.

## Phase 2 - wide pull (801 videos, 60 days) + 15 winners downloaded and inspected

Files: `yt_wide_2026-10-21.json`. Winners were downloaded for private analysis only (cut rate, first frames, speech, loudness).

Caveat found while inspecting: an "English" title does NOT mean an English audience. The "6 Scary Rules" channel narrates in mixed Hindi/Urdu + English; many top
"English" hits are from India/Pakistan channels. Two of the 17 winners I tried to download (an emotional Subway Surfers story, a 18M-view elephant moral story) had been removed within weeks.

| what winners look like | evidence |
|---|---|
| AI-generated MOTION clips of cute/funny animals or toddlers, Pixar-like or photoreal, 10-25 s, almost no speech | AI cats 13.6M / 7.2M / 2.9M views from 1-19k-sub channels; toddler emotional story 2.0M from a 1.2k-sub channel; cuts 3-15 per clip |
| Game-avatar skits (Roblox / Minecraft), 10-60 s, text or voiced dialogue | 14.2M (16k subs), 18.3M (73k subs), 15.9M (89k subs); mostly 0-1 cuts/min (one long shot) or 40/min (meme edits) |
| Photoreal AI explainer clips with word-by-word captions (animals, science, engineering) | bird-and-ants 5.0M from 4k subs; parrot beak 4.2M; WTC collapse explainer 686k from a 786-sub channel |
| STILL-image narrated horror ("Night shift as X - 6 rules"), anime key-art style, 60-70 s | 4 videos at 574-815k views from a 30k-sub channel started June 2026; frame 1 is a poster-style title card; a new picture every ~4.5 s (13 cuts/min); Hinglish narration |
| Weakest: text-chat stories, Reddit over gameplay (median ~1.4k views), plain parable, plain mystery | phase 1 |

Takeaways: (1) real motion beats slow-panned stills almost everywhere; (2) the one still-image winner uses poster-style frame 1, strong consistent art, numbered-rules structure and a new picture every ~4-5 s;
(3) short (10-30 s), wordless or lightly worded, emotion/humour premise, word-highlighted captions when there is speech.
