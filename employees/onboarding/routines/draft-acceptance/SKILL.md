# draft-acceptance

Starts when: the work ID is issued
Done by: the model drafts, plain code checks

## What it does
Drafts the acceptance email with the area and the work ID.

## Instructions for the model
Write a short, warm email to tell the student they have been selected for an internship.
- Greet the student by first name and congratulate them.
- Say the internship area exactly as given in the facts.
- Give the work ID exactly as given in the facts, and ask them to use it in all messages.
- Say the team will contact them with the induction details.
- End with: "Kind regards," and "SLT Internship Team".
- Use only the facts. Do not add dates, numbers, links or names.

## Output
Reply with one JSON object only:
{"subject": "", "body": ""}

## Checks (plain code)
Name, area and work ID must be in the email; no other numbers; no placeholders.
