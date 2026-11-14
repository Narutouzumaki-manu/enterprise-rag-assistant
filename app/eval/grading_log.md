# Grading log (golden file SHA-256 9f78d9b8...bf5fc), 14 Nov 2026

Grades are AI-assisted, not hand graded.

Sources of the grades
- full_agent tcs-gold-01..14 and 24..31 (22 rows): grades from a Claude (AI) review,
  entered with a script (fill_grades.py, kept outside the repo).
- full_agent tcs-gold-15..23 and 32..34 (12 rows), single_draft (34 rows) and the 9 original
  agent_no_checker rows: first pass by an AI coding agent from the PDF.
- agent_no_checker, the other 25 rows: copied mechanically from full_agent, because the
  answer text is identical (replay with 0 live requests, 0 differing answers).

Human checks (by the author)
- All 13 non-CORRECT answerable rows (6 full_agent, 7 single_draft) checked against the PDF.
- Random sample of 10 CORRECT rows (seed 2026): tcs-gold-02, 03, 16, 18, 20, 22, 23, 34
  (single_draft), 11 and 12 (full_agent). Disagreements: 0 of 10.
- Spot checks: tcs-gold-04, 09, 18, 30, 31.
- [Teammate blind grading of gold-04, 07, 12, 13: include only if you have the record.]

Notes
- gold-04 (full_agent): UNSUPPORTED_EXTRA. "Table 1" is a pipeline default section label
  for table chunks, not text in the PDF; the figures were right.
- gold-20: the PDF text (p28, "roughly 28,500") and its table (613,069 -> 582,163 = 30,906)
  disagree; the grade is a judgment call.
- Model: nvidia/nemotron-3-ultra-550b-a55b:free, same for all runs per the operator
  (not stored per record).
- Corrections: none so far.