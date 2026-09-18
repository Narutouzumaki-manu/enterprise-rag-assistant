import pymupdf

doc = pymupdf.open()
page = doc.new_page()

page.insert_text((72, 72), "Revenue Overview", fontsize=16)
page.insert_text((72, 100), "Revenue grew steadily this quarter, driven by strong product demand.", fontsize=10)
page.insert_text((72, 115), "The finance team attributes this to improved retention.", fontsize=10)

page.insert_text((72, 150), "Cost Breakdown", fontsize=16)
page.insert_text((72, 175), "Operating costs increased slightly due to hiring.", fontsize=10)

# Draw an actual 3-row x 2-column table grid (needed for find_tables to detect it)
x0, y0 = 72, 210
col_width = 100
row_height = 20
n_rows, n_cols = 3, 2

for r in range(n_rows + 1):
    y = y0 + r * row_height
    page.draw_line((x0, y), (x0 + n_cols * col_width, y))

for c in range(n_cols + 1):
    x = x0 + c * col_width
    page.draw_line((x, y0), (x, y0 + n_rows * row_height))

cells = [
    ["Category", "Amount"],
    ["Revenue", "100000"],
    ["Costs", "45000"],
]
for r, row in enumerate(cells):
    for c, text in enumerate(row):
        page.insert_text((x0 + c * col_width + 5, y0 + r * row_height + 14), text, fontsize=9)

doc.save("tests/fixtures/sample_rich.pdf")
print("sample_rich.pdf created successfully")