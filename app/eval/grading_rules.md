Written before any answer run on golden v1.1, SHA-256 9F78D9B82E4A7CCB2F2449CC28F45EA0A324E0C0507CB38938745EA8914BF5FC

# Grading rules for answer evaluation (fixed before any run)

Each answer is graded BY HAND against the question's reference_answer and the original
PDF. The script never grades. Grades are assigned from this list only:

For ANSWERABLE questions:
- CORRECT: every fact in reference_answer is present with the right value. A rounded
  value counts as CORRECT only if the rounding is stated or obvious (e.g. $30.0 billion
  for US$30,017 million is ROUNDED, see below).
- ROUNDED: right fact, less precise than the reference (e.g. $30.0 billion for
  $30,017 million). Reported separately; counted as correct for the headline only if
  the table shows both counts.
- PARTIAL: some required facts right, others missing; nothing wrong stated.
- WRONG_FIGURE: a stated figure, name, date or direction differs from the PDF.
- REFUSED_ANSWERABLE: the answer is the insufficient-evidence text although the PDF
  contains the answer.
- UNSUPPORTED_EXTRA: the required facts are right but the answer adds a claim not in
  the PDF (list it).
For UNANSWERABLE questions:
- REFUSED_GOOD: the insufficient-evidence text.
- ANSWERED_BAD: any substantive answer (even hedged), or a figure from a related but
  wrong period/metric presented as the answer.

Computed answers (gold-05, gold-13): a correct computed difference is CORRECT.
Never edit a grade after seeing other variants' results. If a grade is later found
wrong, record the correction with date and reason in a separate "corrections" list.
Report always: n per category, the counts per grade, and the limits (one document,
one run, one model).
