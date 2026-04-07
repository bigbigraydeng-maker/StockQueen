"""Add W6 rows to MR (4.2) and V4 (5.2) WF tables in DataPack"""
filepath = "C:/Users/Zhong/Documents/trae_projects/StockQueen/output/datapack_unpacked/word/document.xml"
with open(filepath, "rb") as f:
    content = f.read()

CELL_STYLE_1200 = (
    b'          <w:tcPr>\r\n'
    b'            <w:tcW w:type="dxa" w:w="1200"/>\r\n'
    b'            <w:tcBorders>\r\n'
    b'              <w:top w:val="single" w:color="AACCDD" w:sz="4"/>\r\n'
    b'              <w:left w:val="single" w:color="AACCDD" w:sz="4"/>\r\n'
    b'              <w:bottom w:val="single" w:color="AACCDD" w:sz="4"/>\r\n'
    b'              <w:right w:val="single" w:color="AACCDD" w:sz="4"/>\r\n'
    b'            </w:tcBorders>\r\n'
    b'            <w:shd w:fill="FFFFFF" w:val="clear"/>\r\n'
    b'            <w:tcMar>\r\n'
    b'              <w:top w:type="dxa" w:w="80"/>\r\n'
    b'              <w:left w:type="dxa" w:w="120"/>\r\n'
    b'              <w:bottom w:type="dxa" w:w="80"/>\r\n'
    b'              <w:right w:type="dxa" w:w="120"/>\r\n'
    b'            </w:tcMar>\r\n'
    b'            <w:vAlign w:val="center"/>\r\n'
    b'          </w:tcPr>\r\n'
)

def make_cell(width, text, bold=False, color=b'333333'):
    cell = (
        b'        <w:tc>\r\n'
        + b'          <w:tcPr>\r\n'
        + b'            <w:tcW w:type="dxa" w:w="' + str(width).encode() + b'"/>\r\n'
        + b'            <w:tcBorders>\r\n'
        + b'              <w:top w:val="single" w:color="AACCDD" w:sz="4"/>\r\n'
        + b'              <w:left w:val="single" w:color="AACCDD" w:sz="4"/>\r\n'
        + b'              <w:bottom w:val="single" w:color="AACCDD" w:sz="4"/>\r\n'
        + b'              <w:right w:val="single" w:color="AACCDD" w:sz="4"/>\r\n'
        + b'            </w:tcBorders>\r\n'
        + b'            <w:shd w:fill="FFFFFF" w:val="clear"/>\r\n'
        + b'            <w:tcMar>\r\n'
        + b'              <w:top w:type="dxa" w:w="80"/>\r\n'
        + b'              <w:left w:type="dxa" w:w="120"/>\r\n'
        + b'              <w:bottom w:type="dxa" w:w="80"/>\r\n'
        + b'              <w:right w:type="dxa" w:w="120"/>\r\n'
        + b'            </w:tcMar>\r\n'
        + b'            <w:vAlign w:val="center"/>\r\n'
        + b'          </w:tcPr>\r\n'
        + b'          <w:p>\r\n'
        + b'            <w:pPr>\r\n'
        + b'              <w:spacing w:after="60" w:before="60"/>\r\n'
        + b'              <w:jc w:val="left"/>\r\n'
        + b'            </w:pPr>\r\n'
        + b'            <w:r>\r\n'
        + b'              <w:rPr>\r\n'
    )
    if bold:
        cell += b'                <w:b/>\r\n                <w:bCs/>\r\n'
    else:
        cell += b'                <w:b w:val="false"/>\r\n                <w:bCs w:val="false"/>\r\n'
    cell += (
        b'                <w:color w:val="' + color + b'"/>\r\n'
        + b'                <w:sz w:val="18"/>\r\n'
        + b'                <w:szCs w:val="18"/>\r\n'
        + b'              </w:rPr>\r\n'
        + b'              <w:t xml:space="preserve">' + text.encode() + b'</w:t>\r\n'
        + b'            </w:r>\r\n'
        + b'          </w:p>\r\n'
        + b'        </w:tc>\r\n'
    )
    return cell

def make_row(cells):
    return b'      <w:tr>\r\n' + cells + b'      </w:tr>\r\n'

# ============================================================
# 1. MR 4.2 table: Add W6 row (W6, 2025, 28, -0.18)
# ============================================================
# Find the end of W5 row in MR 4.2 table
# W5 row ends and has ~1.0, then avg row follows
W5_MR_END = (
    b'<w:t xml:space="preserve">~1.0</w:t>\r\n'
    b'            </w:r>\r\n'
    b'          </w:p>\r\n'
    b'        </w:tc>\r\n'
    b'      </w:tr>\r\n'
)
idx_mr_w5_end = content.find(W5_MR_END)
print(f"MR W5 row end at: {idx_mr_w5_end}")

if idx_mr_w5_end > 0:
    insert_at = idx_mr_w5_end + len(W5_MR_END)
    W6_MR_ROW = make_row(
        make_cell(1200, 'W6') +
        make_cell(1200, '2025') +
        make_cell(3800, '28') +
        make_cell(3880, '-0.18')
    )
    content = content[:insert_at] + W6_MR_ROW + content[insert_at:]
    print(f"Inserted W6 row into MR 4.2 table ({len(W6_MR_ROW)} bytes)")

# ============================================================
# 2. V4 5.2 table: Add W6 row
# ============================================================
# First, let's figure out the V4 5.2 table column structure
# Find section 5.2
idx_52 = content.find(b'5.2  Walk-Forward Results')
print(f"Section 5.2 at: {idx_52}")

# Find W5 in V4 table (after 5.2 section)
idx_v4_w5 = content.find(b'>W5<', idx_52)
print(f"V4 W5 at: {idx_v4_w5}")
if idx_v4_w5 > 0:
    # Find the row start
    v4_w5_row_start = content.rfind(b'      <w:tr>', 0, idx_v4_w5)
    v4_w5_row_end = content.find(b'      </w:tr>\r\n', idx_v4_w5)
    v4_w5_row = content[v4_w5_row_start:v4_w5_row_end + 14]
    import re
    texts = re.findall(rb'<w:t[^>]*>([^<]+)</w:t>', v4_w5_row)
    print(f"V4 W5 row data: {texts}")

    # Get the end byte of W5 row for insertion
    insert_at_v4 = v4_w5_row_end + 14

# Check what comes after V4 W5 row
import re
print(f"Content after V4 W5: {repr(content[insert_at_v4:insert_at_v4+200])}")

with open(filepath, "wb") as f:
    f.write(content)
print(f"Saved {len(content)} bytes")
