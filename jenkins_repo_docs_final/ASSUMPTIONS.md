# Assumptions - Jenkins Quant Project

Use this file to log every approximation, temporary proxy, or unresolved implementation choice.

## Current assumptions
1. The source material is being translated into a testable quant framework, not accepted as proven alpha.
2. Structural pivot/origin selection is a research problem; multiple methods will be tested.
3. TradingView MCP extraction can provide sufficiently reliable historical candles for MVP acquisition, subject to validation.
4. Official experiments will use normalized saved datasets, not live bridge queries.
5. Direct 4H extraction is preferred if complete and stable; otherwise a documented resampling fallback will be used.
6. Weekly bars will use a fixed UTC-based rule, with Monday 00:00 UTC as the default interpretation unless changed in `DECISIONS.md`.
7. Advanced geometric modules remain experimental until MVP modules are validated.

## Logging rule
When a new simplification is introduced, add:
- date
- assumption
- reason
- what it approximates
- how it will later be tested or replaced
