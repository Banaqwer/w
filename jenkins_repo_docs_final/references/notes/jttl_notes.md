# JTTL Notes

## Core idea
The Jenkins True Trend Line is built from a structurally important origin and a root-based projected target.

## Algorithmic interpretation
For origin price `P0`, the classic one-year construct uses a root transform of the origin and places a target line forward in time.

## Quant handling
- origin selection is the difficult part
- the line itself is easier to formalize than the pivot choice
- JTTL should be a projection module, not a standalone trade trigger

## Required tests
- line touch frequency
- line intersection with root horizontals
- crossing-angle behavior
- role inside confluence scoring
