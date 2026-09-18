from docx import Document

d = Document()
d.add_heading("Revenue Overview", level=1)
d.add_paragraph("Revenue grew steadily this quarter, driven by strong product demand.")
d.add_paragraph("The finance team attributes this to improved retention.")

d.add_heading("Cost Breakdown", level=1)
d.add_paragraph("Operating costs increased slightly due to hiring.")

table = d.add_table(rows=3, cols=2)
table.rows[0].cells[0].text = "Category"
table.rows[0].cells[1].text = "Amount"
table.rows[1].cells[0].text = "Revenue"
table.rows[1].cells[1].text = "100000"
table.rows[2].cells[0].text = "Costs"
table.rows[2].cells[1].text = "45000"

d.save("tests/fixtures/sample_rich.docx")
print("sample_rich.docx created successfully")