# SOP: Ingesting the 900-Plaintiff Asset

**Dragonfly Civil — Operations**  
**Version:** 1.0  
**Last Updated:** December 5, 2025

---

## Purpose

This procedure guides you through safely uploading the 900-plaintiff batch from Simplicity into the Dragonfly production system. By following these steps, you will:

1. Confirm the system is healthy before uploading.
2. Upload the file and verify all rows processed correctly.
3. Know exactly what to do if something goes wrong.

---

## A. Pre-Flight Checklist (Before Uploading Anything)

Complete each item before proceeding to the upload step.

- [ ] **1. Confirm you are on the Production dashboard**

  - The URL should be: `https://dragonfly-dashboard.vercel.app`
  - Do NOT use any URL with "localhost" or "dev" in it.

- [ ] **2. Confirm you have the correct CSV file**

  - File name should match what Simplicity provided (e.g., `simplicity_900.csv`).
  - Open it briefly in Excel to confirm it has data (not blank).
  - Row count should be approximately **900** (plus one header row).

- [ ] **3. Check System Status**

  - Navigate to the **Ops Console** page.
  - Look at the **System Status** panel at the top.
  - Confirm all three show **Operational** (green):
    - ✅ API
    - ✅ Database
    - ✅ Workers

- [ ] **4. Glance at the Enrichment Worker widget**
  - It should NOT show a red error banner or "Connection Failed."
  - If it looks normal (numbers, no red warnings), you're good.

**✋ STOP if any of the above are NOT green or look broken. Contact McCabe before proceeding.**

---

## B. Uploading a New Batch

Once pre-flight is complete, follow these steps to upload:

1. Go to the **Ops Console**:  
   `https://dragonfly-dashboard.vercel.app/ops/console`

2. Find the **Intake Station** panel.

3. Either:

   - **Drag and drop** the CSV file onto the upload area, OR
   - Click **Browse** and select the file from your computer.

4. **What you should see immediately:**

   - A new card appears: **Processing Batch #\_\_\_**
   - The filename is displayed (e.g., `simplicity_900.csv`)
   - A progress bar begins moving as rows are processed.

5. **Wait for processing to complete.**  
   This may take 1–3 minutes for 900 rows. Do not refresh the page.

---

## C. Verifying the Batch

After the upload finishes, confirm everything worked:

### Find Your Batch

1. Look at the **Batch History** section.
2. Find the batch with:
   - Your filename (e.g., `simplicity_900.csv`)
   - Today's date and time

### Check the Status

- [ ] **Status pill is GREEN ("Complete")**  
      → This means the batch finished successfully.

- [ ] If the status pill is **RED ("Failed")**, skip to **Section E** below.

### Confirm the Numbers

Click on the batch card to expand it, then verify:

- [ ] **Total rows processed** equals approximately **900**  
      (Should match the invoice count from Simplicity.)

- [ ] **Error count** is **0** (or a very small number, like 1–3).

- [ ] **Success count** equals **Total rows minus errors**.

**If all boxes above are checked, proceed to Section D.**

---

## D. The Radar Check (Spot-Check That Cases Exist)

This quick check confirms the plaintiffs actually made it into the system.

1. Go to the **Dashboard** home page (or **Enforcement Radar** if available).

2. Look for a list or table showing **Recent Judgments** or **New Cases**.

3. Sort by **Date Created** (newest first) if that option exists.

4. **Confirm:**

   - [ ] You see new cases from today's date.
   - [ ] The plaintiff names look like real names (not empty or garbled).
   - [ ] The dollar amounts look realistic (not $0.00 or blank).

5. You do NOT need to check every single row—just confirm the data looks right.

**If the Radar Check looks good, proceed to Section F (Post-Run Checklist).**

---

## E. What To Do If a Batch Fails (Red Status)

If the batch shows **Failed** (red pill), follow these steps carefully:

### Immediate Steps

1. **Click on the failed batch card** to see error details.

2. **Read the error summary.**  
   Common messages you might see:

   - `validation_error` — something wrong with the file format
   - `intake_upload_failed` — system couldn't process the file
   - `duplicate_case_number` — some rows already exist

3. **Take a screenshot** of:

   - The Batch History panel showing the failed batch.
   - The error details displayed when you clicked the batch.

4. **Do NOT re-upload the same file repeatedly.**  
   Multiple failed uploads can create confusion and duplicate data.

5. **Notify McCabe immediately:**

   - 📱 Text message: _(McCabe's number)_
   - 💬 Discord: `#pipeline-alerts` channel

6. **Save the CSV file** to the shared folder:  
   `INTAKE_ISSUES` (on the shared drive)

---

### Safe to Retry vs. Do Not Touch

| Situation                                      | What To Do                               |
| ---------------------------------------------- | ---------------------------------------- |
| McCabe explicitly says "try once more"         | ✅ You may re-upload ONE more time       |
| You're unsure what went wrong                  | ❌ Do NOT re-upload. Wait for guidance.  |
| Batch shows partial success (some rows failed) | ❌ Do NOT re-upload. McCabe will handle. |

**Default rule: One upload per file. When in doubt, ask first.**

---

## F. Post-Run Checklist

After a successful upload, record the following information:

### Confirm These Numbers

- [ ] At least **95%** of rows processed successfully.
- [ ] The **Judgments Ingested** widget on the Ops Console increased by approximately the right amount (close to 900).

### Record the Upload Details

Fill in this log (write by hand or copy to a document):

| Field                   | Value                    |
| ----------------------- | ------------------------ |
| **Date/Time of Upload** | **********\_\_********** |
| **File Name**           | **********\_\_********** |
| **Total Rows**          | **********\_\_********** |
| **Successful Rows**     | **********\_\_********** |
| **Error Count**         | **********\_\_********** |
| **Batch ID**            | **********\_\_********** |
| **Your Initials**       | **********\_\_********** |

---

## Quick Reference Card

| Step | Action                                | ✓   |
| ---- | ------------------------------------- | --- |
| 1    | Confirm Production URL                | ☐   |
| 2    | Verify CSV file is correct            | ☐   |
| 3    | Check System Status = Operational     | ☐   |
| 4    | Upload file via Intake Station        | ☐   |
| 5    | Wait for batch to complete            | ☐   |
| 6    | Verify batch shows "Complete" (green) | ☐   |
| 7    | Confirm row counts match invoice      | ☐   |
| 8    | Radar check: new cases appear         | ☐   |
| 9    | Record upload details in log          | ☐   |

---

## Emergency Contacts

| Role                   | Contact                             |
| ---------------------- | ----------------------------------- |
| **McCabe (Tech Lead)** | Text: _(number)_ / Discord: @mccabe |
| **Discord Channel**    | `#pipeline-alerts`                  |

---

**End of SOP**

_You've got this. Follow the steps, check the boxes, and ask if anything looks wrong._
