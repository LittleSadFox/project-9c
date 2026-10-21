# Daily error logs

Create one file per day: `ERROR_YYYY-MM-DD.md`.
Write in ASD-STE100 Simplified Technical English.
Use short sentences.
Use active voice.
Give one instruction per sentence.

Log errors that the bot, CI, a pod, or the Mac hit that day.
Record the symptom, the cause if you know it, and the next action.
Do not put secrets in these files.
Do not put footage in these files.

## File name

Use the UTC date.

Example: `errors/ERROR_2026-10-21.md`

## Template

```text
# Errors — YYYY-MM-DD

## 1. Short title

- Time (UTC):
- Where: bot computer / CI / pod / Mac
- Symptom:
- Cause:
- Next action:
```

## Current files

No daily error file exists yet.
Add `ERROR_YYYY-MM-DD.md` on the first error of that day.
