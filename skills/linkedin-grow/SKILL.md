---
name: linkedin-grow
description: Use when asked to grow LinkedIn, connect with people on LinkedIn, engage with LinkedIn posts, or boost LinkedIn presence. Triggers on phrases like "grow my LinkedIn", "connect on LinkedIn", "engage LinkedIn feed".
---

# LinkedIn Growth Automation

## Overview

Browser-driven LinkedIn growth session: send connection requests to suggested contacts, engage (like + comment) on relevant posts in your niche, and follow relevant accounts. Paced to stay under LinkedIn's bot-detection thresholds (~15-20 connections/day max).

---

## YOUR PROFILE — edit this before using

```
Name:     [YOUR FULL NAME]
Title:    [YOUR HEADLINE, e.g. "AI Engineer | Full Stack Developer"]
Location: [YOUR CITY, COUNTRY]
Company:  [YOUR CURRENT COMPANY or "Independent"]
Goal:     [e.g. "Remote opportunities, AI clients, dev network"]
Niche:    [e.g. "AI Engineering, Full Stack, Automation"]

Voice for comments: [e.g. "Practical and technical, first-person experience, confident but not salesy"]

Target connections:
  - [Role 1, e.g. AI Engineer]
  - [Role 2, e.g. Engineering Manager]
  - [Role 3, e.g. Tech Recruiter]
  - [Role 4, e.g. CTO / Founder]

Hashtags to engage:
  - #[YourNiche1]
  - #[YourNiche2]
  - #[YourNiche3]
```

---

## Steps

### 1. Connect to Chrome

```
Load: mcp__claude-in-chrome__tabs_context_mcp (createIfEmpty: true)
Load: mcp__claude-in-chrome__navigate
Load: mcp__claude-in-chrome__browser_batch
Load: mcp__claude-in-chrome__computer
```

Navigate to `https://www.linkedin.com/mynetwork/grow/`

### 2. Accept Pending Invitations

Screenshot → find "Invitations" section → click Accept on each pending invite.

### 3. Send Connection Requests (My Network)

Scroll through "People you may know" and "Suggestions for you" sections. Connect with people who have:
- Mutual connections (warm signals)
- Titles matching your target list (from YOUR PROFILE above)
- `#OPENTOWORK` badge (active job seekers — good reciprocal network)

**Pace:** 1 second wait between each Connect click. Stop after ~15-20 requests per session to avoid rate-limiting.

**Skip:** Students only (no title yet), unrelated roles, profiles with no mutual connections and no relevant title.

### 4. Follow Suggested Accounts

At the bottom of feed or My Network page, follow suggested companies and people in your niche.

### 5. Engage With Feed Posts

Navigate to the hashtag search for your primary niche hashtag, sorted by Latest:
`https://www.linkedin.com/search/results/content/?keywords=%23YourHashtag&sortBy=date_posted`

Also check your other niche hashtags from YOUR PROFILE.

For each relevant post (sorted Latest, posted within 24h):
1. **Like** the post
2. **Comment** — write a substantive comment (2-4 sentences) that:
   - Adds a real perspective or insight
   - References specific details from the post (shows you read it)
   - Reflects your identity and niche
   - Never generic ("Great post!", "Thanks for sharing!")

Target 2-3 quality comments per session. Early comments on fresh posts get the most visibility.

### Comment Writing Standards (Anti-Slop)

Before drafting a comment, internally reframe the post's claim as a neutral question ("Is X actually true? Does Y always apply?"), then answer that question honestly. This prevents reflexive agreement.

**Rules:**
- **State a position directly.** No "it depends" unless you immediately name what it depends on and how.
- **Specific beats general.** "This breaks when you have >10k rows and no index" beats "performance can be a concern."
- **One strong sentence > three weak ones.** If a sentence doesn't add information, cut it.
- **If you disagree with the post's premise, say so first**, then offer the alternative. Respectful disagreement gets more engagement than agreement.

**Hard bans — never write these:**
- "Great post!" / "Thanks for sharing!" / "So true!"
- "As an AI..." or any AI self-reference
- "I completely agree" as an opener
- Hedges: "It's worth noting that...", "One might argue...", "In some cases..."
- Ending with a generic question just to drive engagement ("What do you think?")

**Good comment shape:**
> [Specific reaction to one concrete detail from the post] + [your experience or counter-angle] + [optional: one tight question that's genuinely curious, not a CTA]

### 6. Home Feed Engagement

Navigate to `https://www.linkedin.com/feed/`

Scroll through — like posts from:
- Direct connections sharing work/achievements
- High-engagement posts in your niche (VP/Director level)
- Posts that align with your target hashtags

---

## Rate Limits (Stay Safe)

| Action | Safe Daily Limit |
|--------|-----------------|
| Connection requests | 15-20 |
| Likes | 50-100 |
| Comments | 5-10 |
| Follows | 20-30 |

Exceeding these triggers LinkedIn's automated restrictions. Space sessions across the day if running multiple times.

---

## Common Mistakes

- **Connecting with everyone blindly** — prioritize mutual connections and relevant titles
- **Generic comments** — LinkedIn's algorithm demotes them; write real thoughts
- **Too many requests too fast** — LinkedIn will restrict the account
- **Commenting on old posts** — sort by Latest for maximum visibility
