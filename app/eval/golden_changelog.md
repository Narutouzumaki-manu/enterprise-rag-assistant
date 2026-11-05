# Golden Dataset Changelog

## [v1.1] - 2026-11-05

### Summary
Update from v1 to v1.1 to eliminate overlap with Member 2's tuned question pool (`data/eval/retrieval_questions.json`) and expand evaluation coverage.

### Replaced Questions (2)
- **`tcs-gold-11`**:
  - **OLD**: *"How many clients above $100 million in annual revenue did TCS have at the end of FY26, and how did that compare with the year before?"*
  - **NEW**: *"How many TCS clients were in the $50 million and above revenue band at 31 March 2026, and how much had that number grown over the year?"*
  - **Reason**: SAME_QUESTION as tuned q09 / q04 (data/eval/retrieval_questions.json); replaced before any agent output was seen.
- **`tcs-gold-22`**:
  - **OLD**: *"How did TCS's attrition during FY26 compare with the range management described as its comfort zone?"*
  - **NEW**: *"What was TCS's total contract value in Q1 FY27 for North America, BFSI and Consumer Business?"*
  - **Reason**: SAME_QUESTION as tuned q09 / q04 (data/eval/retrieval_questions.json); replaced before any agent output was seen.

### Appended Questions (3)
- **`tcs-gold-32`**: *"What was TCS's voluntary attrition rate for IT services in Q1 FY27, and how much total cash and investments did it hold at the end of that quarter?"* (category: `multi_fact`, style: `paraphrase`)
- **`tcs-gold-33`**: *"What revenue did TCS report for the January-to-March quarter of the financial year before FY26?"* (category: `fact_lookup`, style: `paraphrase`)
- **`tcs-gold-34`**: *"What share of TCS revenue came from North America and from BFSI in Q4 FY26?"* (category: `multi_fact`, style: `paraphrase`)

### Dropped Candidate Questions
- **`gold-35`**: Dropped because it is SAME_QUESTION as q11 (*"What was reported net profit in Q3 FY26 and how much did it fall year on year?"* under paraphrase of the quarter carrying the labour-code charge).

### Statistics
- Total Questions: 34 (25 answerable, 9 unanswerable)
- Independent Questions (not in `flagged_same_fact`): 30 (21 answerable, 9 unanswerable)

The validator expects the TCS report PDF at data/eval/documents/.

FROZEN v1.1 - SHA-256 9F78D9B82E4A7CCB2F2449CC28F45EA0A324E0C0507CB38938745EA8914BF5FC - 34 questions (25 answerable, 9 unanswerable; 21 + 9 independent of the tuned pool).