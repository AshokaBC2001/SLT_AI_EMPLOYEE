# reply-failed-or-hold

Starts when: the result is Fail or Hold
Done by: the model drafts, plain code checks

## What it does
Drafts the rejection email after a Fail, or a "result pending" note after a Hold.

## Instructions for the model
Write a short, kind email to the student about their interview result, as described in the facts
("message_type" is "rejection" or "hold").
- rejection: thank them for attending, say we cannot offer a place this time, wish them well.
  Do not say "congratulations".
- hold: thank them for attending, say the result is on hold and we will contact them when a
  decision is made.
- Greet the student by first name.
- Do not repeat the interviewer's comments.
- End with: "Kind regards," and "SLT Internship Team".
- Use only the facts. Do not add dates, numbers, links or names.

## Output
Reply with one JSON object only:
{"subject": "", "body": ""}
