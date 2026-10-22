# invite-and-slots

Starts when: the status is "Shortlisted"
Done by: plain code picks the slot, the model drafts the invitation, plain code checks it

## What it does
Picks the next free interview slot on a working day and drafts the invitation email.

## Instructions for the model
Write a short, friendly interview invitation email to the student.
- Greet the student by first name.
- Say the interview is for the internship area given in the facts.
- Give the interview date and time exactly as written in the facts.
- Mention the application number from the facts.
- Ask the student to reply to confirm.
- End with: "Kind regards," and "SLT Internship Team".
- Use only the facts. Do not add other dates, times, numbers, links or names.

## Output
Reply with one JSON object only:
{"subject": "", "body": ""}

## Checks (plain code)
Name, area and slot must be in the email; no numbers that are not in the facts; no
placeholders such as [Name]; 25 to 260 words.
