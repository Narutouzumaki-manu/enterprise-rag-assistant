from docx import Document

d = Document()
d.add_paragraph("This is the first paragraph about revenue growth.")
d.add_paragraph("This is the second paragraph about quarterly performance.")
d.add_paragraph("This is the third paragraph about future outlook.")
d.save("tests/fixtures/sample.docx")

print("sample.docx created successfully")