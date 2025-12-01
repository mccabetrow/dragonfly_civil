# Dragonfly Ops Playbook v1

**For: Ops Lead (Mom Edition)**  
**Last Updated: November 2025**

---

## What Is Dragonfly?

Dragonfly is our judgment-enforcement operating system. It helps us:

- **Track plaintiffs** – people who won court judgments and want help collecting what they're owed.
- **Prioritize outreach** – the system ranks who to call first based on case value and likelihood of success.
- **Log every interaction** – calls, agreements, and status changes all get recorded so nothing falls through the cracks.
- **Move cases through enforcement** – from first contact → agreement signed → money collected.

Think of it as a smart to-do list that tells you who to call, when, and keeps a paper trail of everything.

---

## Your Role: Ops Lead

You are the human connection between Dragonfly and our plaintiffs.

**Your job is to:**

- Work the **Call Queue** every day
- Log every call outcome (reached, voicemail, bad number, etc.)
- Update plaintiff status when things change
- Flag anything weird to me (errors, missing data, confused plaintiffs)

**You do NOT need to:**

- Fix database errors (that's my job)
- Understand the code
- Worry if something breaks – just write it down and keep going

---

## Daily Checklist

### ☀️ Morning (Start of Day)

- [ ] Open the **Dashboard** and go to the **Call Queue** tab
- [ ] Check how many plaintiffs are in today's queue (aim: 15–25 calls/day)
- [ ] Review the top 5 names – click each to see their **Plaintiff Detail** page
- [ ] Note any flagged issues (red badges, missing phone numbers)
- [ ] If the queue is empty, check **Tasks** tab for follow-ups due today

### 🌤️ Midday (After ~10 Calls)

- [ ] Take a break!
- [ ] Quick scan of **Tasks** tab – any urgent follow-ups?
- [ ] If you're stuck on someone's case, add a note and move on
- [ ] Check that your logged calls are showing in **Timeline** (peace of mind)

### 🌙 Afternoon (End of Day)

- [ ] Finish remaining calls or reschedule to tomorrow
- [ ] Log any callbacks you promised (use the follow-up date field)
- [ ] Quick count: How many calls made today? Write it down.
- [ ] Close the dashboard – you're done!

---

## Weekly Checklist

### 📅 Monday

- [ ] Check if any new plaintiffs were imported over the weekend
- [ ] Review **Plaintiff Funnel** numbers (new → contacted → signed)
- [ ] Set a goal for the week: "I'll contact X new plaintiffs"

### 📅 Friday

- [ ] Review the week's calls – how many reached? How many agreements?
- [ ] Note any plaintiffs who need extra attention next week
- [ ] Send me a quick update: calls made, agreements sent, any issues

---

## Call Script (Keep It Simple)

**Opening:**

> "Hi, this is [Your Name] calling from Dragonfly Civil. Is this [Plaintiff Name]?"

**If yes:**

> "I'm reaching out because you have an outstanding judgment from [Case Reference]. We help people like you collect what they're owed. Do you have a few minutes to talk?"

**If they're interested:**

> "Great! I'd like to confirm a few details and explain how we can help. First, is [phone/address] still the best way to reach you?"

**If they're hesitant:**

> "No pressure at all. I can send you some information by mail or email, and you can reach out when you're ready. What works best for you?"

**Closing (interested):**

> "I'll send over our agreement today. Once you sign, we'll get started right away. Any questions before I let you go?"

**Closing (not interested / bad timing):**

> "No problem. I'll make a note and we can follow up another time. Have a great day!"

---

## Troubleshooting: If X Happens, Do Y

### ❌ "The Call Queue is empty"

| Check This                         | What To Do                                        |
| ---------------------------------- | ------------------------------------------------- |
| Is it early in the day?            | Wait 15 min – the system refreshes periodically   |
| Did we just import new plaintiffs? | Go to **Tasks** tab – they may show there first   |
| Still empty after 30 min?          | Write it down and tell me – might be a data issue |

### ❌ "I see an error message (RPC error, DB error, red text)"

| What To Do                                     |
| ---------------------------------------------- |
| Screenshot it (or write down the exact words)  |
| Note what you clicked right before it happened |
| Refresh the page – often fixes it              |
| If it keeps happening, stop and message me     |

**Do NOT panic.** Errors don't delete anything. They just mean something didn't save properly.

### ❌ "I can't log a call outcome"

| Check This                        | What To Do                                                |
| --------------------------------- | --------------------------------------------------------- |
| Is the plaintiff selected?        | Click their name in the queue first                       |
| Are all required fields filled?   | Outcome and notes are usually required                    |
| Does the Save/Log button respond? | If it's grayed out, you're missing something              |
| Still stuck?                      | Write the outcome on paper, tell me, I'll log it manually |

### ❌ "A plaintiff says they already talked to someone"

| What To Do                                                           |
| -------------------------------------------------------------------- |
| Check their **Timeline** – do you see a previous call logged?        |
| If yes, review the notes before continuing                           |
| If no, it might be a different company – clarify who they spoke with |
| Log this call with a note about what they said                       |

### ❌ "The phone number is wrong"

| What To Do                                          |
| --------------------------------------------------- |
| Log the call as "bad_number"                        |
| Add a note: "Number disconnected" or "Wrong person" |
| Move on – the system will flag it for data cleanup  |

---

## Quick Reference: Dashboard Tabs

| Tab                  | What It Shows                 | When To Use It              |
| -------------------- | ----------------------------- | --------------------------- |
| **Call Queue**       | Plaintiffs ranked by priority | Your main workspace         |
| **Plaintiff Detail** | Full info on one plaintiff    | Before/during a call        |
| **Timeline**         | History of all interactions   | To see what happened before |
| **Tasks**            | Follow-ups and to-dos         | For scheduled callbacks     |
| **Pipeline**         | Overall case flow stats       | Weekly review               |

---

## Golden Rules

1. **Log everything.** Even "no answer" is valuable data.
2. **When in doubt, write it down.** Paper notes → tell me later.
3. **You can't break it.** The system is designed to handle mistakes.
4. **Ask questions.** There are no dumb questions, only dumb bugs (which are my fault).

---

## Emergency Contact

**If the whole system is down or you're stuck:**

- Text/call me immediately
- Do NOT keep clicking things hoping it fixes itself
- Take a break – it's okay

---

_You've got this. The system is here to help you, not the other way around._ 💪
