# choose-area

Starts when: the profile is ready
Done by: the model, checked by plain code, with a second opinion from the scoring rules

## What it does
Chooses the internship area that fits the student best, with reasons and evidence.

## Instructions for the model
Choose the ONE area from the list that fits this student best.
- Use the area names exactly as written in the list.
- If the student clearly fits none of the areas, do not force one. Answer
  "New area: <short name>" (for example "New area: Human Resources").
- If you cannot tell, answer "Needs human review".
- reasons: 1 to 3 short sentences saying why.
- evidence: 1 to 4 short phrases copied exactly from the CV that support your choice.

## Output
Reply with one JSON object only:
{"area": "", "reasons": [], "evidence": []}

## Checks (plain code)
- The area must be on the list, a "New area: ..." suggestion, or "Needs human review".
- At least one evidence phrase must really be written in the CV.
- Second opinion: the scoring rules also pick the best area. If they disagree strongly, the
  candidate is marked for the HR officer.

## If the checks keep failing
The area with the best rule score is used if at least half of its required skills are in the
CV. Otherwise the HR officer chooses the area.
