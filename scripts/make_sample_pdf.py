import fitz  # PyMuPDF

doc = fitz.open()

page1 = doc.new_page()
page1.insert_text((72, 72), "This is page one. It talks about revenue growth in Q1.")

page2 = doc.new_page()
page2.insert_text((72, 72), "This is page two. It talks about quarterly performance metrics.")

doc.save("tests/fixtures/sample.pdf")
print("sample.pdf created successfully")