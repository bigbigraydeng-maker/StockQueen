"""Update IM document with W6 Walk-Forward data"""
filepath = "C:/Users/Zhong/Documents/trae_projects/StockQueen/output/im_unpacked/word/document.xml"
with open(filepath, "rb") as f:
    content = f.read()

em = b'\xe2\x80\x93'  # en dash
EM = b'\xe2\x80\x94'  # em dash

# ============================================================
# 1. Insert W6 row into IM WF table (before Average row)
# ============================================================
# The IM table has W1-W5 with F5F7FA Average row following
# Find W5 row end and Average row start
# W5 row ends with </w:tr>\n then Average row starts

# W5 row end is at 143884
w5_row_end = 143884
insert_at = w5_row_end + 14  # after </w:tr>\r\n

# IM table columns: Window(1200), Year(1500), MarketRegime(3300), PortfolioOOS(3360)
W6_IM_ROW = (
    b'      <w:tr>\r\n'
    b'        <w:tc>\r\n'
    b'          <w:tcPr>\r\n'
    b'            <w:tcW w:type="dxa" w:w="1200"/>\r\n'
    b'            <w:tcMar>\r\n'
    b'              <w:top w:type="dxa" w:w="80"/>\r\n'
    b'              <w:left w:type="dxa" w:w="120"/>\r\n'
    b'              <w:bottom w:type="dxa" w:w="80"/>\r\n'
    b'              <w:right w:type="dxa" w:w="120"/>\r\n'
    b'            </w:tcMar>\r\n'
    b'            <w:vAlign w:val="top"/>\r\n'
    b'          </w:tcPr>\r\n'
    b'          <w:p>\r\n'
    b'            <w:r>\r\n'
    b'              <w:rPr>\r\n'
    b'                <w:rFonts w:ascii="Calibri" w:cs="Calibri" w:eastAsia="Calibri" w:hAnsi="Calibri"/>\r\n'
    b'                <w:b w:val="false"/>\r\n'
    b'                <w:bCs w:val="false"/>\r\n'
    b'                <w:sz w:val="20"/>\r\n'
    b'                <w:szCs w:val="20"/>\r\n'
    b'              </w:rPr>\r\n'
    b'              <w:t xml:space="preserve">W6</w:t>\r\n'
    b'            </w:r>\r\n'
    b'          </w:p>\r\n'
    b'        </w:tc>\r\n'
    b'        <w:tc>\r\n'
    b'          <w:tcPr>\r\n'
    b'            <w:tcW w:type="dxa" w:w="1500"/>\r\n'
    b'            <w:tcMar>\r\n'
    b'              <w:top w:type="dxa" w:w="80"/>\r\n'
    b'              <w:left w:type="dxa" w:w="120"/>\r\n'
    b'              <w:bottom w:type="dxa" w:w="80"/>\r\n'
    b'              <w:right w:type="dxa" w:w="120"/>\r\n'
    b'            </w:tcMar>\r\n'
    b'            <w:vAlign w:val="top"/>\r\n'
    b'          </w:tcPr>\r\n'
    b'          <w:p>\r\n'
    b'            <w:r>\r\n'
    b'              <w:rPr>\r\n'
    b'                <w:rFonts w:ascii="Calibri" w:cs="Calibri" w:eastAsia="Calibri" w:hAnsi="Calibri"/>\r\n'
    b'                <w:b w:val="false"/>\r\n'
    b'                <w:bCs w:val="false"/>\r\n'
    b'                <w:sz w:val="20"/>\r\n'
    b'                <w:szCs w:val="20"/>\r\n'
    b'              </w:rPr>\r\n'
    b'              <w:t xml:space="preserve">2025</w:t>\r\n'
    b'            </w:r>\r\n'
    b'          </w:p>\r\n'
    b'        </w:tc>\r\n'
    b'        <w:tc>\r\n'
    b'          <w:tcPr>\r\n'
    b'            <w:tcW w:type="dxa" w:w="3300"/>\r\n'
    b'            <w:tcMar>\r\n'
    b'              <w:top w:type="dxa" w:w="80"/>\r\n'
    b'              <w:left w:type="dxa" w:w="120"/>\r\n'
    b'              <w:bottom w:type="dxa" w:w="80"/>\r\n'
    b'              <w:right w:type="dxa" w:w="120"/>\r\n'
    b'            </w:tcMar>\r\n'
    b'            <w:vAlign w:val="top"/>\r\n'
    b'          </w:tcPr>\r\n'
    b'          <w:p>\r\n'
    b'            <w:r>\r\n'
    b'              <w:rPr>\r\n'
    b'                <w:rFonts w:ascii="Calibri" w:cs="Calibri" w:eastAsia="Calibri" w:hAnsi="Calibri"/>\r\n'
    b'                <w:b w:val="false"/>\r\n'
    b'                <w:bCs w:val="false"/>\r\n'
    b'                <w:sz w:val="20"/>\r\n'
    b'                <w:szCs w:val="20"/>\r\n'
    b'              </w:rPr>\r\n'
    b'              <w:t xml:space="preserve">Tariff Uncertainty</w:t>\r\n'
    b'            </w:r>\r\n'
    b'          </w:p>\r\n'
    b'        </w:tc>\r\n'
    b'        <w:tc>\r\n'
    b'          <w:tcPr>\r\n'
    b'            <w:tcW w:type="dxa" w:w="3360"/>\r\n'
    b'            <w:tcMar>\r\n'
    b'              <w:top w:type="dxa" w:w="80"/>\r\n'
    b'              <w:left w:type="dxa" w:w="120"/>\r\n'
    b'              <w:bottom w:type="dxa" w:w="80"/>\r\n'
    b'              <w:right w:type="dxa" w:w="120"/>\r\n'
    b'            </w:tcMar>\r\n'
    b'            <w:vAlign w:val="top"/>\r\n'
    b'          </w:tcPr>\r\n'
    b'          <w:p>\r\n'
    b'            <w:r>\r\n'
    b'              <w:rPr>\r\n'
    b'                <w:rFonts w:ascii="Calibri" w:cs="Calibri" w:eastAsia="Calibri" w:hAnsi="Calibri"/>\r\n'
    b'                <w:b w:val="false"/>\r\n'
    b'                <w:bCs w:val="false"/>\r\n'
    b'                <w:sz w:val="20"/>\r\n'
    b'                <w:szCs w:val="20"/>\r\n'
    b'              </w:rPr>\r\n'
    b'              <w:t xml:space="preserve">3.148</w:t>\r\n'
    b'            </w:r>\r\n'
    b'          </w:p>\r\n'
    b'        </w:tc>\r\n'
    b'      </w:tr>\r\n'
)

content = content[:insert_at] + W6_IM_ROW + content[insert_at:]
print(f"Inserted W6 row into IM WF table ({len(W6_IM_ROW)} bytes)")

# ============================================================
# 2. Text replacements
# ============================================================
replacements = [
    # Average row: 4.886 -> 4.606
    (b'>4.886</w:t>\r\n            </w:r>\r\n          </w:p>\r\n        </w:tc>\r\n      </w:tr>\r\n    </w:tbl>',
     b'>4.606</w:t>\r\n            </w:r>\r\n          </w:p>\r\n        </w:tc>\r\n      </w:tr>\r\n    </w:tbl>'),

    # Walk-forward validated... paragraph (intro)
    (b'walk-forward validated Portfolio OOS Sharpe of 4.886 (V4+MR Dual Strategy) on U.S. equity markets over a 5-year out-of-sample period (2020\xe2\x80\x932024).',
     b'walk-forward validated Portfolio OOS Sharpe of 4.606 (V4+MR Dual Strategy) on U.S. equity markets over a 6-year out-of-sample period (2020\xe2\x80\x932025).'),

    # Bullet: 4.886 / 5-yr CAGR 14.2% / +94.3%
    (b'4.886 / 5-yr CAGR 14.2% / +94.3% cumulative (V4+MR Dual Strategy, walk-forward validated)',
     b'4.606 / 6-yr CAGR 13.9% / +118.0% cumulative (V4+MR Dual Strategy, walk-forward validated)'),

    # Core strategy WF results table: avg OOS sharpe
    (b'4.886 (Portfolio avg; V4: 1.364, MR: 0.959)',
     b'4.606 (Portfolio avg; V4: 1.322, MR: 0.770)'),

    # 4 out of 5 positive (80%)
    (b'4 out of 5 positive (80%); Worst: W3 2022 = -1.3% vs SPY -19%',
     b'5 out of 6 positive (83%); Worst: W3 2022 = -1.3% vs SPY -19%'),

    # CAGR 14.2%
    (b'>14.2%</w:t>\r\n            </w:r>\r\n          </w:p>\r\n        </w:tc>\r\n      </w:tr>',
     b'>13.9%</w:t>\r\n            </w:r>\r\n          </w:p>\r\n        </w:tc>\r\n      </w:tr>'),

    # +94.3% in metrics table
    (b'>+94.3%</w:t>\r\n            </w:r>\r\n          </w:p>\r\n        </w:tc>\r\n      </w:tr>',
     b'>+118.0%</w:t>\r\n            </w:r>\r\n          </w:p>\r\n        </w:tc>\r\n      </w:tr>'),

    # 5 Windows (2020-2024) in the table
    (b'>5 Windows (2020-2024)</w:t>',
     b'>6 Windows (2020-2025)</w:t>'),

    # "4.886" standalone in metrics table (Sharpe Ratio row)
    # (there are multiple, so target the metrics table specifically)

    # "5 windows." in text
    (b'5 windows.</w:t>',
     b'6 windows.</w:t>'),

    # "5 windows positive; worst -1.3%"
    (b'5 windows positive; worst -1.3%)',
     b'6 windows positive; worst -1.3%)'),

    # "(Yes (4/5 windows positive; worst -1.3%)"
    (b'(Yes (4/5 windows positive; worst -1.3%))',
     b'(Yes (5/6 windows positive; worst -1.3%))'),

    # Overfitting decay text
    (b'OOS Sharpe 1.364 (V4; Portfolio avg 4.886)). A decay below 0.4 confirms the strategy has a real, persistent edge \xe2\x80\x94 not a curve-fitted artifact. Parameter consistency: top_n=3 was selected by the optimizer in all 5 independent windows, confirming structural robustness.',
     b'OOS Sharpe 1.322 (V4; Portfolio avg 4.606)). A decay below 0.4 confirms the strategy has a real, persistent edge \xe2\x80\x94 not a curve-fitted artifact. Parameter consistency: top_n=3 was selected by the optimizer in all 6 independent windows, confirming structural robustness.'),

    # Walk-Forward Validation Yes
    (b'Yes (4/5 windows positive; worst -1.3%)',
     b'Yes (5/6 windows positive; worst -1.3%)'),

    # StockQueen V4: 0.26 footnote in last table
    (b'StockQueen V4: 0.26 (low and acceptable).',
     b'StockQueen V4: 0.26 (low and acceptable).'),  # no change needed

    # Independent verification / GHA run
    (b'(Run #23423631911), executed 2026-03-23',
     b'(W1-W5: Run #23423631911; W6: Run #23446074874)'),
]

for old, new in replacements:
    count = content.count(old)
    if count == 0:
        print(f"WARNING not found: {repr(old[:80])}")
    else:
        content = content.replace(old, new)
        print(f"OK ({count}x): {repr(old[:80])}")

# Handle remaining 4.886 occurrences (in Sharpe Ratio metric rows)
# Check what remains
remaining_4886 = []
start = 0
while True:
    idx = content.find(b'4.886', start)
    if idx == -1: break
    remaining_4886.append(idx)
    start = idx + 1

print(f"\nRemaining 4.886 at: {remaining_4886}")
for p in remaining_4886:
    print(f"  pos {p}: {repr(content[p-50:p+60])}")

with open(filepath, "wb") as f:
    f.write(content)
print(f"\nSaved {len(content)} bytes")
