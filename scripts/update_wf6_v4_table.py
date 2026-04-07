"""Add W6 row to V4 5.2 WF table in DataPack"""
filepath = "C:/Users/Zhong/Documents/trae_projects/StockQueen/output/datapack_unpacked/word/document.xml"
with open(filepath, "rb") as f:
    content = f.read()

def make_cell(width, text, bold=False):
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
        b'                <w:color w:val="333333"/>\r\n'
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

# V4 5.2 table columns: Window(800), Year(800), MarketRegime(1800), Sharpe(1300), Stability(5380)
# W6: W6, 2025, Tariff Uncertainty, 1.11, Stable
import re
idx_52 = content.find(b'5.2  Walk-Forward Results')
idx_v4_w5 = content.find(b'>W5<', idx_52)
v4_w5_row_start = content.rfind(b'      <w:tr>', 0, idx_v4_w5)
v4_w5_row_end = content.find(b'      </w:tr>', idx_v4_w5)
insert_at = v4_w5_row_end + 14

print(f"V4 W5 row end: {v4_w5_row_end}, insert at: {insert_at}")

W6_V4_ROW = make_row(
    make_cell(800, 'W6') +
    make_cell(800, '2025') +
    make_cell(1800, 'Tariff Uncertainty') +
    make_cell(1300, '1.11') +
    make_cell(5380, 'Stable')
)

content = content[:insert_at] + W6_V4_ROW + content[insert_at:]
print(f"Inserted W6 row into V4 5.2 table ({len(W6_V4_ROW)} bytes)")

with open(filepath, "wb") as f:
    f.write(content)
print(f"Saved {len(content)} bytes")
