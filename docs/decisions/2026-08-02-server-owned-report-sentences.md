# Keep generated report claims in server-owned sentences

**Decision:** The LLM may select two to four eligible sentence templates, but it
may not author report prose. The server owns each sentence and interpolates only
the evidence keys declared for that template.

**Context:** The previous boundary rejected unknown numbers, malformed
placeholders, and non-Korean text. It still accepted unsupported qualitative
claims with no number or placeholder, including predictions of success or
growth. Prompt instructions could not make those statements trustworthy.

**Why:** A closed template enum makes every public claim traceable to a known
database field while preserving the model's useful choice of what to emphasize.
It also removes language and numeric heuristics that could only detect some bad
outputs after generation.

**Rejected:**

- Tighten the prompt: this remains advisory and cannot close the contract.
- Add a qualitative phrase blacklist: it is incomplete by construction and
  creates a growing policy parser.
- Remove the LLM call: deterministic reports are safer but remove the requested
  evidence-selection behavior entirely.

**Status:** Active.
