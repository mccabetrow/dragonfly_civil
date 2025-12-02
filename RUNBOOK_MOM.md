# RUNBOOK_MOM

Friendly call-center checklist for Mom’s shift. Everything below is step-by-step with spots for screenshots we will fill in later.

---

## How to log in to the dashboard

![Dashboard Login Screenshot](docs/dashboard_login.png)

1. Open Chrome and click the **Dragonfly Dashboard** bookmark on the bookmarks bar.
2. When the login screen appears, type the shared email and password from the sticky note in the drawer; keep Caps Lock off so the password matches.
3. Click **Sign In** and wait for the spinning circle to finish; the Pipeline tab should load automatically.
4. If the browser says “session expired,” press `Ctrl+Shift+R` to refresh and try once more; after two failed attempts, ping Dad or engineering.

---

## How to open the Call Queue

![Call Queue Screenshot](docs/call_queue.png)

1. Inside the dashboard, look at the left sidebar and click **Pipeline** if it is not already highlighted.
2. Scroll until you see the **Call Queue** card with the table of names—this is Mom’s working list.
3. Press the **Refresh** button in the top-right corner of the card to make sure you are looking at the newest data.
4. Sort the table by **Due** by clicking that column header so the most urgent calls float to the top.

---

## What each column means

![Call Queue Columns Screenshot](docs/call_queue_columns.png)

1. **Plaintiff** – who we are calling; click the name to open their profile if you need background.
2. **Tier** – red = Tier A (call first), amber = Tier B (call next), blue = Tier C (call if time allows).
3. **Due** – the date and time the call is expected; anything overdue shows in red text.
4. **Status** – current state of the call (New, Follow-up, Completed). Follow-ups mean the person asked for another time.
5. **Contact** – shows phone number and any notes about best times; hover the info icon to see extra hints.
6. **Actions** – the buttons you press after each conversation (`Call`, `Outcome`, `Schedule Follow-Up`).

---

## Steps to call a plaintiff and log outcome

![Call Outcome Screenshot](docs/call_outcome.png)

1. Start with the top row in the queue and tap the phone icon next to the number when you are ready to dial.
2. Let the phone ring at least six times; if there is no answer, leave the standard voicemail script from the binder.
3. After the call (or voicemail), click the **Outcome** button on that row to open the update form.
4. Pick one of the options from the dropdown:
   - `Reached + Next Steps` when you spoke and agreed on an action.
   - `Left Voicemail` when you left the script.
   - `Bad Number` when the line is disconnected.
   - `Do Not Call` when they explicitly decline.
5. Type a short note (who you spoke with, promised callback time, anything notable) and set a follow-up date if needed.
6. Press **Save Outcome**; the row will disappear if the task is closed or drop lower if you scheduled a future follow-up.

### Using the dedicated Call Queue page

1. Click **Call Queue** in the left navigation to jump straight into today’s due and overdue calls.
2. Work the list from top to bottom: press **Log Outcome**, choose the best-fit outcome, set the follow-up time when needed, then click **Save Outcome**.
3. After finishing a batch of calls, hit the browser refresh button (or `Ctrl+R`) so the queue pulls in any newly due tasks.

---

## What to do if something looks wrong

![Issue Screenshot](docs/dashboard_issue.png)

1. If the queue is empty but you know calls are due, hit **Refresh** once and wait ten seconds.
2. If the numbers look wrong (e.g., all zeros, missing tiers, blank names), take a screenshot with `Windows Key + Shift + S`.
3. Check Slack `#daily-ops` to see if there is an outage note; if not, post your screenshot with a short description.
4. While waiting for help, flip to the paper backup list in the call binder so calls can continue.
5. When engineering replies that things are fixed, refresh the dashboard and confirm the data looks normal before resuming.

---

Keep this card at your station. Read each section out loud the first time you do it each day so the flow stays consistent.

---

## How to refresh the demo dashboard when dev feels weird

If buttons stop responding or the call queue looks empty in dev, run the bundled reset script before escalating.

1. In VS Code, open a PowerShell terminal and run:

   ```powershell
   cd C:\Users\mccab\dragonfly_civil
   $env:SUPABASE_MODE = 'dev'
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo_reset_and_smoke.ps1
   ```

2. Wait for the message `Demo reset + smoke checks completed successfully.` The script seeds the deterministic plaintiffs, runs the plaintiff + enforcement smoke checks, and triggers the demo pipeline so a fresh case shows up (timeout 180 seconds).
3. Refresh the dashboard in Chrome. The call queue, pipeline, and task list should snap back to the expected demo state.
4. Still off? Screenshot the issue, note that you ran the reset script, and ping engineering in `#daily-ops`.

---

## How to load the 900-case demo file

When the sales team wants the big plaintiff list in dev, follow these steps.

1. Replace `run/plaintiffs_canonical.csv` with the latest 900-case CSV (keep the original somewhere safe in case you must revert).
2. In a VS Code PowerShell terminal run:

   ```powershell
   cd C:\Users\mccab\dragonfly_civil
   $env:DEMO_ENV = 'demo'
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\import_900_demo.ps1
   ```

3. Watch for the JSON summary containing `demo_900_<timestamp>` under `[OK] Running demo bulk intake`; copy that block into Slack so everyone knows which batch is live.
4. Run the demo reset + smoke script afterward to regenerate the dashboards with the new data, then refresh Chrome before presenting.
