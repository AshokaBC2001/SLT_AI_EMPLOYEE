# prepare-questions

Starts when: the status is "Shortlisted"
Done by: the model, checked by plain code

## What it does
Writes interview questions for the interviewer, based on the profile and the skill gaps.

## Instructions for the model
Write 5 or 6 interview questions for this student.
- At least one question about a project in the profile.
- At least one question about a skill gap, if there are gaps.
- One question about why they chose this area.
- Simple, clear questions. Each one ends with a question mark.

## Output
Reply with one JSON object only:
{"questions": []}

## Checks (plain code)
4 to 8 questions, each a full sentence ending with "?".

## If the checks keep failing
Standard questions made from the area and the gaps are used instead.
