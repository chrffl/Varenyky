# Erasmus Inbox Agent

## The task

A university Erasmus office receives student documents by email (Learning Agreement, transcript, insurance, certificate of arrival) with random file names like `scan_0042.pdf` or `IMG_2231.jpg`. Today staff open every email, rename and file each document, and type the dates into Excel by hand.

We are building an AI agent that does this automatically:

1. Reads every email in the `inbox/` folder
2. Works out the student, the document type and the academic year
3. Saves the file as `filed/Surname_Name/Surname_Name_DocType_2026-27.pdf`
4. Adds the key dates (start and end of stay, host university) to `students.xlsx`, one row per student
5. Answers common student questions from a short FAQ and passes everything else to staff

**Stack:** Python, Google ADK, Gemini API, openpyxl
**Time:** 4 hours
**Data:** fake test data only, no real student information

## Team

| Member | Part of the project |
|---|---|
| **Polina** — team lead | Repository setup, FAQ for student questions, merging branches, demo script and presentation |
| **Diana** — file tools | Reading emails, renaming and saving attachments into student folders, writing data to Excel |
| **Serhii** — agent | Creating the agent in ADK, teaching Gemini to read documents, connecting the tools and FAQ, final results table |
| **Yuliia** — test data | Generating 10 fake emails with PDF attachments (including messy ones), testing the agent and reporting bugs |

## Plan

| Time | What |
|---|---|
| 0:00–0:30 | Setup: Python, Gemini API key, clone repo |
| 0:30–2:30 | Everyone works on their own part |
| 2:30–3:15 | Merge everything and run the full agent |
| 3:15–3:45 | Fix bugs |
| 3:45–4:00 | Demo rehearsal |

## Demo (3 minutes)

Drop 10 messy emails in, press go: renamed files appear in folders, the spreadsheet fills up, and the agent answers a student question live.

## How to run

```bash
# 1. virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS

# 2. dependencies
pip install -r requirements.txt

# 3. environment: copy .env_example to .env and fill in
#    GOOGLE_API_KEY=...        (Gemini API key)
#    ERASMUS_MODEL=gemini-2.5-flash   (or another available Gemini model)

# 4. generate 10 fake emails with PDF attachments into inbox/
python scripts/generate_samples.py

# 5. run the agent (ADK dev UI)
adk run erasmus_inbox

# 6. run the offline tests (no API key needed)
python -m pytest tests/ -v
```
