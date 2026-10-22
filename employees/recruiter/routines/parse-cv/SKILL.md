# parse-cv

Starts when: the status is "New CV"
Done by: the model, checked by plain code

## What it does
Reads the CV text and writes a short profile: name, email, phone, education, skills, projects
and experience.

## Instructions for the model
Read the CV below and copy the facts into a profile.
- Copy words from the CV. Do not add anything that is not written in it.
- name: the student's full name as written at the top of the CV.
- email and phone: exactly as written, or "" if the CV has none.
- education: one item per degree, diploma or school, with the institute.
- skills: short names of tools, languages and abilities (for example "Python", "Docker").
- projects: one item per project, a short line with the project name and what it used.
- experience: one item per job or internship. Use [] if there is none.

## Output
Reply with one JSON object only:
{"name": "", "email": "", "phone": "", "education": [], "skills": [], "projects": [], "experience": []}

## Checks (plain code)
- The name, email and phone must be written in the CV.
- Every list item must be written in the CV. Items that are not are removed.
- If many items are not in the CV, the model is asked to fix its answer.

## If the checks keep failing
A profile made by simple rules is used instead, and the candidate is marked for the HR officer.
