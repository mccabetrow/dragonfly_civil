# Mom Enforcement Console — User Guide

> **For:** Mom (Ops Director)  
> **Version:** 1.0  
> **Last Updated:** December 2025

---

## Quick Reference

| Item             | Value                                      |
| ---------------- | ------------------------------------------ |
| **Console URL**  | `https://dragonfly-mom-console.vercel.app` |
| **Backup URL**   | `https://dragonfly-staging.vercel.app`     |
| **Help Contact** | McCabe (text or Discord)                   |

---

## Getting Started

### Opening the Console

1. **Open your web browser** (Chrome or Edge recommended)
2. **Go to the URL:** `https://dragonfly-mom-console.vercel.app`
3. The console should load automatically — no login required for now
4. **Bookmark this page** so you can find it easily

> 💡 **Tip:** If the page doesn't load or shows an error, try the backup URL or text McCabe.

---

## The Four Main Tabs

The console has four tabs across the top. Here's what each one does:

### 1. Pipeline Tab 📊

**What it shows:** All cases we're working on, organized by status.

**Think of it as:** Your master list of every judgment in the portfolio.

**What you'll see:**

- Plaintiff name and debtor name
- Current status (New, Enriched, Ready for Call, etc.)
- Tier (1 = high priority, 2 = medium, 3 = lower)
- Days since last action

**When to use it:**

- Get the big picture of where everything stands
- Find specific cases by searching
- See which cases haven't been touched recently

---

### 2. Signatures Tab ✍️

**What it shows:** Documents and actions waiting for your approval.

**Think of it as:** Your "inbox" of things that need a decision.

**What you'll see:**

- Action type (Demand Letter, Garnishment, Settlement, etc.)
- Plaintiff and debtor names
- Date the action was created
- Approve / Reject buttons

**When to use it:**

- First thing every morning
- Before you leave for the day
- Whenever you get a notification that something is pending

**How to approve or reject:**

1. Click on the action to see details
2. Review the information carefully
3. Click **Approve** if it looks correct
4. Click **Reject** if something is wrong — add a note explaining why

> ⚠️ **Important:** Never approve something you're unsure about. When in doubt, reject with a note and ask McCabe or Dad.

---

### 3. Call Queue Tab 📞

**What it shows:** People you should call today, ranked by priority.

**Think of it as:** Your call list for the day.

**What you'll see:**

- Debtor name and phone number
- Reason for the call (initial contact, follow-up, payment reminder)
- Priority score (higher = more important)
- Last contact date
- Notes from previous calls

**When to use it:**

- After checking signatures in the morning
- Throughout the day as you make calls
- To pick your next call when you finish one

**How to use it:**

1. Start from the top of the list (highest priority)
2. Click on a debtor to see their full profile
3. Make the call using the script (see Scripts & Templates doc)
4. Log the outcome (see "Logging Call Outcomes" below)

---

### 4. Activity Tab 📜

**What it shows:** Recent actions and events across all cases.

**Think of it as:** A timeline of everything that's happened.

**What you'll see:**

- Action type and description
- Who did it (you, McCabe, system)
- When it happened
- Which case it relates to

**When to use it:**

- To see what happened while you were away
- To check if an action you took actually went through
- To review history on a specific case

---

## Morning Routine (30-45 minutes)

Do this every morning when you start work:

### Step 1: Check Signatures (10 minutes)

1. Click the **Signatures** tab
2. Review each pending item:
   - Read the action type and details
   - Make sure the names and amounts look correct
   - Check that we're allowed to take this action (see Desk Card)
3. For each item:
   - **Approve** if everything looks right
   - **Reject** with a note if something is wrong
4. Goal: **Clear the signature queue** before making calls

### Step 2: Review Call Queue (5 minutes)

1. Click the **Call Queue** tab
2. Look at the top 10 cases
3. Pick your **top 5 calls** for the morning
4. Click on each one to review:
   - Previous call notes
   - Payment history
   - Any special flags or warnings

### Step 3: Make Your Calls (20-30 minutes)

1. Start with your first pick from the queue
2. Use the appropriate script from `scripts_and_templates.md`
3. After each call, **log the outcome immediately** (see below)
4. Move to the next call
5. Goal: **Complete 5 calls** before lunch

---

## How to Log Call Outcomes

After every call, log what happened:

1. Find the case in the **Pipeline** or **Call Queue** tab
2. Click **Log Call** or **Add Note**
3. Select the outcome:
   - **Reached — Payment Promised** (they said they'll pay)
   - **Reached — Dispute** (they're disputing the debt)
   - **Reached — Hardship** (they can't pay right now)
   - **Reached — Negotiating** (discussing settlement)
   - **No Answer** (phone rang, no pickup)
   - **Voicemail Left** (you left a message)
   - **Wrong Number** (not the right person)
   - **Disconnected** (number doesn't work)
4. Add any notes about the conversation
5. Click **Save**

> 💡 **Tip:** Log outcomes immediately after each call while it's fresh in your mind.

---

## Afternoon Wrap-Up (15 minutes)

Do this before you finish for the day:

### Step 1: Re-check Signatures (5 minutes)

1. Go to **Signatures** tab
2. Approve/reject anything that came in during the day
3. Goal: Leave the queue as empty as possible

### Step 2: Review Your Calls (5 minutes)

1. Go to **Activity** tab
2. Look at your logged calls from today
3. Make sure nothing is missing
4. Note any follow-ups needed for tomorrow

### Step 3: Check for Urgent Items (5 minutes)

1. Go to **Pipeline** tab
2. Sort by "Days Since Last Action" (highest first)
3. Flag anything that's been sitting too long
4. Make a note of what to tackle first tomorrow

---

## Safety & Compliance Reminders

These are the rules you **must** follow on every call. (See `mom_desk_card.md` for the full list.)

### The 10 Always-Do Rules

1. ✅ **Always identify yourself:** "This is [Name] calling from Dragonfly Civil regarding a legal matter."
2. ✅ **Always confirm identity:** "Am I speaking with [Debtor Name]?" before discussing the debt.
3. ✅ **Always state the Mini-Miranda** on first contact: "This is an attempt to collect a debt. Any information obtained will be used for that purpose."
4. ✅ **Always note the time** — only call between **8 AM and 9 PM** in the debtor's time zone.
5. ✅ **Always log every call** immediately after hanging up.
6. ✅ **Always stop calling** if they say "stop calling" or "don't contact me again."
7. ✅ **Always offer validation** if they dispute: "You have the right to request validation of this debt in writing."
8. ✅ **Always be respectful** — never yell, threaten, or use bad language.
9. ✅ **Always escalate** attorney representation or legal threats to Dad immediately.
10. ✅ **Always protect privacy** — never discuss the debt with anyone except the debtor.

### The 10 Never-Do Rules

1. ❌ **Never call before 8 AM or after 9 PM** in the debtor's time zone.
2. ❌ **Never discuss the debt with family, friends, or employers.**
3. ❌ **Never threaten arrest, jail, or lawsuits you can't actually file.**
4. ❌ **Never lie about who you are or what you're calling about.**
5. ❌ **Never call repeatedly to harass** — max 1-2 calls per day.
6. ❌ **Never continue calling** after a cease-and-desist request.
7. ❌ **Never contact someone who says they have an attorney** — escalate to Dad.
8. ❌ **Never add fake fees or inflate the debt amount.**
9. ❌ **Never post about debtors on social media.**
10. ❌ **Never skip logging a call** — if it's not logged, it didn't happen.

---

## Common Situations

### "I'm disputing this debt"

1. Say: "You have the right to dispute this debt. Would you like to send a written dispute?"
2. Log as **Reached — Dispute**
3. Do NOT continue collection efforts until dispute is resolved
4. Flag for follow-up

### "I can't afford to pay"

1. Say: "I understand. Would you like to discuss a payment plan?"
2. If yes, discuss options (see settlement templates)
3. Log as **Reached — Hardship** with notes on their situation
4. Flag for potential settlement offer

### "I have a lawyer handling this"

1. Say: "I understand. Can you provide your attorney's name and contact information?"
2. **Stop the call** — do not discuss the debt further
3. Log as **Reached — Attorney Representation**
4. **Immediately escalate to Dad**

### "Stop calling me"

1. Say: "I understand. We will cease telephone contact."
2. **Stop the call politely**
3. Log as **Cease and Desist Requested**
4. The system will flag this — do not call again

### Wrong number or disconnected

1. Log as **Wrong Number** or **Disconnected**
2. The system will try to find a better number
3. Move to your next call

---

## Troubleshooting

### The console won't load

1. Try refreshing the page (Ctrl+R or Cmd+R)
2. Try the backup URL
3. Check your internet connection
4. Text McCabe

### I approved something by mistake

1. **Don't panic** — most actions can be reversed
2. Text McCabe immediately with the case name
3. Note what happened so we can fix it

### I'm not sure if I should approve something

1. **Reject it** with a note: "Need clarification"
2. Text McCabe or Dad to review
3. Better to delay than approve something wrong

### The call queue is empty

1. Check the **Pipeline** tab for cases marked "Ready for Call"
2. If there's nothing, great! You're caught up.
3. Review older cases that might need follow-up

### I made a call but forgot to log it

1. Log it as soon as you remember
2. Note in the comments that it was logged late
3. Try to remember the key details

---

## Quick Keyboard Shortcuts

| Shortcut           | Action                 |
| ------------------ | ---------------------- |
| `Ctrl+F` / `Cmd+F` | Search on current page |
| `F5`               | Refresh the page       |
| `Tab`              | Move between fields    |
| `Enter`            | Submit / Confirm       |

---

## Getting Help

- **Technical issues:** Text McCabe
- **Compliance questions:** Ask Dad or check `mom_desk_card.md`
- **Unsure about a case:** Reject with a note and ask

---

## Daily Checklist

Print this and keep it at your desk:

```
☐ Open console and check it loads
☐ Clear signature queue (approve/reject all)
☐ Pick top 5 calls from queue
☐ Make morning calls (aim for 5)
☐ Log all call outcomes
☐ Lunch break
☐ Afternoon calls (aim for 5 more)
☐ Re-check signature queue
☐ Log any remaining outcomes
☐ Check for urgent/overdue items
☐ Note tomorrow's priorities
☐ Done for the day!
```

---

_You've got this! If anything is confusing, just ask. We're building this together._
