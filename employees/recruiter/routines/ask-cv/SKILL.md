# ask-cv

Starts when: a person asks a question about a candidate's CV
Done by: the model, checked by plain code against the CV text

## What it does
Answers a question from the HR officer or Interviewer using only facts written in the candidate's CV, and quotes the exact supporting phrases from the CV.

## Instructions for the model
Answer the question below using ONLY what is written in the CV.
- Be short, clear and honest (1 to 3 sentences).
- Do not guess or invent anything that is not in the CV. If the CV does not mention it, say clearly that it is not mentioned in the CV.
- quotes: 1 to 3 short phrases or sentences copied verbatim from the CV that support your answer (or [] if the CV does not mention it).

## Output
Reply with one JSON object only:
{"answer": "", "quotes": []}

## Checks (plain code)
- The answer must be between 5 and 120 words and contain no placeholders.
- Every quote must really be written in the CV.

## If the checks keep failing
Plain code searches the CV for sentences matching the question keywords and returns them directly.
