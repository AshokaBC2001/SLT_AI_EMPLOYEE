# morning-brief

Done by: the model writes, plain code checks the numbers

## What it does
Writes a short brief for the HR officer from the facts.

## Instructions for the model
Write a short morning brief for the HR officer in plain English, 60 to 150 words.
- Start with what needs a person today.
- Then say what the AI employees did in the last 24 hours.
- Mention stalled candidates if there are any.
- Use only the numbers in the facts. Do not add other numbers.
- Do not use student names.

## Output
Reply with one JSON object only:
{"brief": ""}

## Checks (plain code)
Every number in the brief must be in the facts. 25 to 220 words.

## If the checks keep failing
A brief made from a template is used instead.
