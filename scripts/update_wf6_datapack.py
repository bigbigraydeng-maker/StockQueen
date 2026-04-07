"""
Update DataPack and IM docx files with W6 Walk-Forward data.
"""
import re

def update_datapack():
    filepath = "C:/Users/Zhong/Documents/trae_projects/StockQueen/output/datapack_unpacked/word/document.xml"
    with open(filepath, "rb") as f:
        content = f.read()

    # 1. Insert W6 row into main WF table (section 3.2)
    # Find the insertion point: after </w:tr> of W5 row (which contains +11.8%)
    # The first +11.8% after section 3.2 is at byte 231938
    # The </w:tr> after it is at byte 232007

    W5_END_MARKER = b'+11.8%</w:t>\r\n            </w:r>\r\n          </w:p>\r\n        </w:tc>\r\n      </w:tr>\r\n      <w:tr>\r\n        <w:tc>\r\n          <w:tcPr>\r\n            <w:tcW w:type="dxa" w:w="600"/>\r\n            <w:tcBorders>\r\n              <w:top w:val="single" w:color="AACCDD" w:sz="4"/>\r\n              <w:left w:val="single" w:color="AACCDD" w:sz="4"/>\r\n              <w:bottom w:val="single" w:color="AACCDD" w:sz="4"/>\r\n              <w:right w:val="single" w:color="AACCDD" w:sz="4"/>\r\n            </w:tcBorders>\r\n            <w:shd w:fill="EEF5F9" w:val="clear"/>'

    # We need to find the first occurrence of this pattern (in main WF table)
    idx = content.find(W5_END_MARKER)
    if idx == -1:
        print("ERROR: Could not find W5 row end marker")
        # Try to find the end of W5 row another way
        idx_118 = content.find(b'+11.8%</w:t>\r\n            </w:r>\r\n          </w:p>\r\n        </w:tc>\r\n      </w:tr>\r\n')
        print(f"Simplified marker at: {idx_118}")
        return

    print(f"Found W5 end marker at: {idx}")

    # The split point is after the W5 </w:tr>, which is:
    # everything up to and including </w:tr>\r\n, then the Average row starts
    W5_TR_END = b'+11.8%</w:t>\r\n            </w:r>\r\n          </w:p>\r\n        </w:tc>\r\n      </w:tr>\r\n'
    split_idx = content.find(W5_TR_END) + len(W5_TR_END)
    print(f"Insertion point at byte: {split_idx}")
    print(f"Content at insertion: {repr(content[split_idx:split_idx+50])}")

    # W6 row XML
    W6_ROW = (
        b'      <w:tr>\r\n'
        b'        <w:tc>\r\n'
        b'          <w:tcPr>\r\n'
        b'            <w:tcW w:type="dxa" w:w="600"/>\r\n'
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
        b'          <w:p>\r\n'
        b'            <w:pPr>\r\n'
        b'              <w:spacing w:after="60" w:before="60"/>\r\n'
        b'              <w:jc w:val="left"/>\r\n'
        b'            </w:pPr>\r\n'
        b'            <w:r>\r\n'
        b'              <w:rPr>\r\n'
        b'                <w:b w:val="false"/>\r\n'
        b'                <w:bCs w:val="false"/>\r\n'
        b'                <w:color w:val="333333"/>\r\n'
        b'                <w:sz w:val="18"/>\r\n'
        b'                <w:szCs w:val="18"/>\r\n'
        b'              </w:rPr>\r\n'
        b'              <w:t xml:space="preserve">W6</w:t>\r\n'
        b'            </w:r>\r\n'
        b'          </w:p>\r\n'
        b'        </w:tc>\r\n'
        b'        <w:tc>\r\n'
        b'          <w:tcPr>\r\n'
        b'            <w:tcW w:type="dxa" w:w="800"/>\r\n'
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
        b'          <w:p>\r\n'
        b'            <w:pPr>\r\n'
        b'              <w:spacing w:after="60" w:before="60"/>\r\n'
        b'              <w:jc w:val="left"/>\r\n'
        b'            </w:pPr>\r\n'
        b'            <w:r>\r\n'
        b'              <w:rPr>\r\n'
        b'                <w:b w:val="false"/>\r\n'
        b'                <w:bCs w:val="false"/>\r\n'
        b'                <w:color w:val="333333"/>\r\n'
        b'                <w:sz w:val="18"/>\r\n'
        b'                <w:szCs w:val="18"/>\r\n'
        b'              </w:rPr>\r\n'
        b'              <w:t xml:space="preserve">2025</w:t>\r\n'
        b'            </w:r>\r\n'
        b'          </w:p>\r\n'
        b'        </w:tc>\r\n'
        b'        <w:tc>\r\n'
        b'          <w:tcPr>\r\n'
        b'            <w:tcW w:type="dxa" w:w="2200"/>\r\n'
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
        b'          <w:p>\r\n'
        b'            <w:pPr>\r\n'
        b'              <w:spacing w:after="60" w:before="60"/>\r\n'
        b'              <w:jc w:val="left"/>\r\n'
        b'            </w:pPr>\r\n'
        b'            <w:r>\r\n'
        b'              <w:rPr>\r\n'
        b'                <w:b w:val="false"/>\r\n'
        b'                <w:bCs w:val="false"/>\r\n'
        b'                <w:color w:val="333333"/>\r\n'
        b'                <w:sz w:val="18"/>\r\n'
        b'                <w:szCs w:val="18"/>\r\n'
        b'              </w:rPr>\r\n'
        b'              <w:t xml:space="preserve">Tariff uncertainty</w:t>\r\n'
        b'            </w:r>\r\n'
        b'          </w:p>\r\n'
        b'        </w:tc>\r\n'
        b'        <w:tc>\r\n'
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
        b'          <w:p>\r\n'
        b'            <w:pPr>\r\n'
        b'              <w:spacing w:after="60" w:before="60"/>\r\n'
        b'              <w:jc w:val="left"/>\r\n'
        b'            </w:pPr>\r\n'
        b'            <w:r>\r\n'
        b'              <w:rPr>\r\n'
        b'                <w:b w:val="false"/>\r\n'
        b'                <w:bCs w:val="false"/>\r\n'
        b'                <w:color w:val="333333"/>\r\n'
        b'                <w:sz w:val="18"/>\r\n'
        b'                <w:szCs w:val="18"/>\r\n'
        b'              </w:rPr>\r\n'
        b'              <w:t xml:space="preserve">1.11</w:t>\r\n'
        b'            </w:r>\r\n'
        b'          </w:p>\r\n'
        b'        </w:tc>\r\n'
        b'        <w:tc>\r\n'
        b'          <w:tcPr>\r\n'
        b'            <w:tcW w:type="dxa" w:w="1100"/>\r\n'
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
        b'          <w:p>\r\n'
        b'            <w:pPr>\r\n'
        b'              <w:spacing w:after="60" w:before="60"/>\r\n'
        b'              <w:jc w:val="left"/>\r\n'
        b'            </w:pPr>\r\n'
        b'            <w:r>\r\n'
        b'              <w:rPr>\r\n'
        b'                <w:b w:val="false"/>\r\n'
        b'                <w:bCs w:val="false"/>\r\n'
        b'                <w:color w:val="333333"/>\r\n'
        b'                <w:sz w:val="18"/>\r\n'
        b'                <w:szCs w:val="18"/>\r\n'
        b'              </w:rPr>\r\n'
        b'              <w:t xml:space="preserve">-0.18</w:t>\r\n'
        b'            </w:r>\r\n'
        b'          </w:p>\r\n'
        b'        </w:tc>\r\n'
        b'        <w:tc>\r\n'
        b'          <w:tcPr>\r\n'
        b'            <w:tcW w:type="dxa" w:w="1680"/>\r\n'
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
        b'          <w:p>\r\n'
        b'            <w:pPr>\r\n'
        b'              <w:spacing w:after="60" w:before="60"/>\r\n'
        b'              <w:jc w:val="left"/>\r\n'
        b'            </w:pPr>\r\n'
        b'            <w:r>\r\n'
        b'              <w:rPr>\r\n'
        b'                <w:b w:val="false"/>\r\n'
        b'                <w:bCs w:val="false"/>\r\n'
        b'                <w:color w:val="333333"/>\r\n'
        b'                <w:sz w:val="18"/>\r\n'
        b'                <w:szCs w:val="18"/>\r\n'
        b'              </w:rPr>\r\n'
        b'              <w:t xml:space="preserve">3.148</w:t>\r\n'
        b'            </w:r>\r\n'
        b'          </w:p>\r\n'
        b'        </w:tc>\r\n'
        b'        <w:tc>\r\n'
        b'          <w:tcPr>\r\n'
        b'            <w:tcW w:type="dxa" w:w="1500"/>\r\n'
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
        b'          <w:p>\r\n'
        b'            <w:pPr>\r\n'
        b'              <w:spacing w:after="60" w:before="60"/>\r\n'
        b'              <w:jc w:val="left"/>\r\n'
        b'            </w:pPr>\r\n'
        b'            <w:r>\r\n'
        b'              <w:rPr>\r\n'
        b'                <w:b w:val="false"/>\r\n'
        b'                <w:bCs w:val="false"/>\r\n'
        b'                <w:color w:val="333333"/>\r\n'
        b'                <w:sz w:val="18"/>\r\n'
        b'                <w:szCs w:val="18"/>\r\n'
        b'              </w:rPr>\r\n'
        b'              <w:t xml:space="preserve">+12.0%</w:t>\r\n'
        b'            </w:r>\r\n'
        b'          </w:p>\r\n'
        b'        </w:tc>\r\n'
        b'      </w:tr>\r\n'
    )

    # Insert W6 row at split_idx
    new_content = content[:split_idx] + W6_ROW + content[split_idx:]
    print(f"Inserted W6 row ({len(W6_ROW)} bytes) at position {split_idx}")

    # Now do all text replacements on new_content
    replacements = [
        # Average row: 5 windows -> 6 windows (only the one in Average row of WF table)
        # Use first occurrence of "5 windows</w:t>" in the Average row context
        (b'>5 windows</w:t>\r\n            </w:r>\r\n          </w:p>\r\n        </w:tc>\r\n        <w:tc>\r\n          <w:tcPr>\r\n            <w:tcW w:type="dxa" w:w="2200"/>\r\n            <w:tcBorders>\r\n              <w:top w:val="single" w:color="AACCDD" w:sz="4"/>\r\n              <w:left w:val="single" w:color="AACCDD" w:sz="4"/>\r\n              <w:bottom w:val="single" w:color="AACCDD" w:sz="4"/>\r\n              <w:right w:val="single" w:color="AACCDD" w:sz="4"/>\r\n            </w:tcBorders>\r\n            <w:shd w:fill="EEF5F9" w:val="clear"/>',
         b'>6 windows</w:t>\r\n            </w:r>\r\n          </w:p>\r\n        </w:tc>\r\n        <w:tc>\r\n          <w:tcPr>\r\n            <w:tcW w:type="dxa" w:w="2200"/>\r\n            <w:tcBorders>\r\n              <w:top w:val="single" w:color="AACCDD" w:sz="4"/>\r\n              <w:left w:val="single" w:color="AACCDD" w:sz="4"/>\r\n              <w:bottom w:val="single" w:color="AACCDD" w:sz="4"/>\r\n              <w:right w:val="single" w:color="AACCDD" w:sz="4"/>\r\n            </w:tcBorders>\r\n            <w:shd w:fill="EEF5F9" w:val="clear"/>'),
    ]

    for old, new in replacements:
        count = new_content.count(old)
        if count == 0:
            print(f"WARNING: Not found: {repr(old[:60])}")
        else:
            new_content = new_content.replace(old, new, 1)
            print(f"Replaced (1x): {repr(old[:60])}")

    # Simple text replacements (global - need to be careful)
    # For the Average row: 1.364->1.322, 0.959->0.770, 4.886->4.606, +94.3%->+118.0%
    # These are in bold cells in the EEF5F9 (avg row) context
    # The em-dash in 2020-2024 is \xe2\x80\x93
    em = b'\xe2\x80\x93'

    # 2020-2024 -> 2020-2025 (only in avg row, identified by EEF5F9 shading)
    old_2024 = b'>2020' + em + b'2024</w:t>\r\n            </w:r>\r\n          </w:p>\r\n        </w:tc>\r\n        <w:tc>\r\n          <w:tcPr>\r\n            <w:tcW w:type="dxa" w:w="1200"/>\r\n            <w:tcBorders>\r\n              <w:top w:val="single" w:color="AACCDD" w:sz="4"/>\r\n              <w:left w:val="single" w:color="AACCDD" w:sz="4"/>\r\n              <w:bottom w:val="single" w:color="AACCDD" w:sz="4"/>\r\n              <w:right w:val="single" w:color="AACCDD" w:sz="4"/>\r\n            </w:tcBorders>\r\n            <w:shd w:fill="EEF5F9" w:val="clear"/>'
    new_2025 = b'>2020' + em + b'2025</w:t>\r\n            </w:r>\r\n          </w:p>\r\n        </w:tc>\r\n        <w:tc>\r\n          <w:tcPr>\r\n            <w:tcW w:type="dxa" w:w="1200"/>\r\n            <w:tcBorders>\r\n              <w:top w:val="single" w:color="AACCDD" w:sz="4"/>\r\n              <w:left w:val="single" w:color="AACCDD" w:sz="4"/>\r\n              <w:bottom w:val="single" w:color="AACCDD" w:sz="4"/>\r\n              <w:right w:val="single" w:color="AACCDD" w:sz="4"/>\r\n            </w:tcBorders>\r\n            <w:shd w:fill="EEF5F9" w:val="clear"/>'

    count = new_content.count(old_2024)
    print(f"2020-2024 in avg row found: {count}")
    if count > 0:
        new_content = new_content.replace(old_2024, new_2025, 1)
        print("Replaced 2020-2024 -> 2020-2025 in avg row")

    # Now replace the bold numeric values in the avg row
    # 1.364 (bold) -> 1.322
    old_1364 = b'<w:b/>\r\n                <w:bCs/>\r\n                <w:color w:val="333333"/>\r\n                <w:sz w:val="18"/>\r\n                <w:szCs w:val="18"/>\r\n              </w:rPr>\r\n              <w:t xml:space="preserve">1.364</w:t>'
    new_1322 = b'<w:b/>\r\n                <w:bCs/>\r\n                <w:color w:val="333333"/>\r\n                <w:sz w:val="18"/>\r\n                <w:szCs w:val="18"/>\r\n              </w:rPr>\r\n              <w:t xml:space="preserve">1.322</w:t>'
    count = new_content.count(old_1364)
    print(f"1.364 bold occurrences: {count}")
    new_content = new_content.replace(old_1364, new_1322)

    # 0.959 (bold) -> 0.770
    old_0959 = b'<w:b/>\r\n                <w:bCs/>\r\n                <w:color w:val="333333"/>\r\n                <w:sz w:val="18"/>\r\n                <w:szCs w:val="18"/>\r\n              </w:rPr>\r\n              <w:t xml:space="preserve">0.959</w:t>'
    new_0770 = b'<w:b/>\r\n                <w:bCs/>\r\n                <w:color w:val="333333"/>\r\n                <w:sz w:val="18"/>\r\n                <w:szCs w:val="18"/>\r\n              </w:rPr>\r\n              <w:t xml:space="preserve">0.770</w:t>'
    count = new_content.count(old_0959)
    print(f"0.959 bold occurrences: {count}")
    new_content = new_content.replace(old_0959, new_0770)

    # 4.886 (bold) -> 4.606 in the avg row
    old_4886_bold = b'<w:b/>\r\n                <w:bCs/>\r\n                <w:color w:val="333333"/>\r\n                <w:sz w:val="18"/>\r\n                <w:szCs w:val="18"/>\r\n              </w:rPr>\r\n              <w:t xml:space="preserve">4.886</w:t>'
    new_4606 = b'<w:b/>\r\n                <w:bCs/>\r\n                <w:color w:val="333333"/>\r\n                <w:sz w:val="18"/>\r\n                <w:szCs w:val="18"/>\r\n              </w:rPr>\r\n              <w:t xml:space="preserve">4.606</w:t>'
    count = new_content.count(old_4886_bold)
    print(f"4.886 bold occurrences: {count}")
    new_content = new_content.replace(old_4886_bold, new_4606)

    # +94.3% (bold) -> +118.0%
    old_943_bold = b'<w:b/>\r\n                <w:bCs/>\r\n                <w:color w:val="333333"/>\r\n                <w:sz w:val="18"/>\r\n                <w:szCs w:val="18"/>\r\n              </w:rPr>\r\n              <w:t xml:space="preserve">+94.3%</w:t>'
    new_118_bold = b'<w:b/>\r\n                <w:bCs/>\r\n                <w:color w:val="333333"/>\r\n                <w:sz w:val="18"/>\r\n                <w:szCs w:val="18"/>\r\n              </w:rPr>\r\n              <w:t xml:space="preserve">+118.0%</w:t>'
    count = new_content.count(old_943_bold)
    print(f"+94.3% bold occurrences: {count}")
    new_content = new_content.replace(old_943_bold, new_118_bold)

    # Write back
    with open(filepath, "wb") as f:
        f.write(new_content)
    print(f"\nSaved DataPack document.xml ({len(new_content)} bytes)")

update_datapack()
