# score-match

Starts when: an area from the list is chosen
Done by: plain code (the model never gives the score)

## What it does
Scores the CV against the area's requirements, out of 100:
- Skills 40: share of the area's required skills found in the CV
- Projects 30: up to 2 projects related to the area
- Education 20: a related subject gets 20, any other study gets 10
- Experience 10: related experience gets 10, any other experience gets 5

The weights are in hiring/config.py and the area requirements are on the Areas page.
