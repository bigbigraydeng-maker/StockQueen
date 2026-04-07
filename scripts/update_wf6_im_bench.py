"""Add W6 row to IM benchmark comparison table and update avg row"""
filepath = "C:/Users/Zhong/Documents/trae_projects/StockQueen/output/im_unpacked/word/document.xml"
with open(filepath, "rb") as f:
    content = f.read()

# W6 row for IM benchmark table (same 7 columns as DataPack benchmark table)
W6_IM_BENCH_ROW = b"""      <w:tr>
        <w:tc>
          <w:tcPr>
            <w:tcW w:type="dxa" w:w="900"/>
            <w:tcMar>
              <w:top w:type="dxa" w:w="60"/>
              <w:bottom w:type="dxa" w:w="60"/>
              <w:left w:type="dxa" w:w="100"/>
              <w:right w:type="dxa" w:w="100"/>
            </w:tcMar>
          </w:tcPr>
          <w:p>
            <w:r>
              <w:rPr>
                <w:sz w:val="16"/>
              </w:rPr>
              <w:t>W6 2025</w:t>
            </w:r>
          </w:p>
        </w:tc>
        <w:tc>
          <w:tcPr>
            <w:tcW w:type="dxa" w:w="1560"/>
            <w:tcMar>
              <w:top w:type="dxa" w:w="60"/>
              <w:bottom w:type="dxa" w:w="60"/>
              <w:left w:type="dxa" w:w="100"/>
              <w:right w:type="dxa" w:w="100"/>
            </w:tcMar>
          </w:tcPr>
          <w:p>
            <w:r>
              <w:rPr>
                <w:sz w:val="16"/>
              </w:rPr>
              <w:t>Tariff Uncertainty</w:t>
            </w:r>
          </w:p>
        </w:tc>
        <w:tc>
          <w:tcPr>
            <w:tcW w:type="dxa" w:w="1200"/>
            <w:tcMar>
              <w:top w:type="dxa" w:w="60"/>
              <w:bottom w:type="dxa" w:w="60"/>
              <w:left w:type="dxa" w:w="100"/>
              <w:right w:type="dxa" w:w="100"/>
            </w:tcMar>
          </w:tcPr>
          <w:p>
            <w:pPr>
              <w:jc w:val="center"/>
            </w:pPr>
            <w:r>
              <w:rPr>
                <w:b/>
                <w:color w:val="1a6e3a"/>
                <w:sz w:val="16"/>
              </w:rPr>
              <w:t>3.148</w:t>
            </w:r>
          </w:p>
        </w:tc>
        <w:tc>
          <w:tcPr>
            <w:tcW w:type="dxa" w:w="1560"/>
            <w:tcMar>
              <w:top w:type="dxa" w:w="60"/>
              <w:bottom w:type="dxa" w:w="60"/>
              <w:left w:type="dxa" w:w="100"/>
              <w:right w:type="dxa" w:w="100"/>
            </w:tcMar>
          </w:tcPr>
          <w:p>
            <w:pPr>
              <w:jc w:val="center"/>
            </w:pPr>
            <w:r>
              <w:rPr>
                <w:b/>
                <w:color w:val="1a6e3a"/>
                <w:sz w:val="16"/>
              </w:rPr>
              <w:t>+12.0%</w:t>
            </w:r>
          </w:p>
        </w:tc>
        <w:tc>
          <w:tcPr>
            <w:tcW w:type="dxa" w:w="1200"/>
            <w:tcMar>
              <w:top w:type="dxa" w:w="60"/>
              <w:bottom w:type="dxa" w:w="60"/>
              <w:left w:type="dxa" w:w="100"/>
              <w:right w:type="dxa" w:w="100"/>
            </w:tcMar>
          </w:tcPr>
          <w:p>
            <w:pPr>
              <w:jc w:val="center"/>
            </w:pPr>
            <w:r>
              <w:rPr>
                <w:sz w:val="16"/>
              </w:rPr>
              <w:t>\xe2\x80\x94</w:t>
            </w:r>
          </w:p>
        </w:tc>
        <w:tc>
          <w:tcPr>
            <w:tcW w:type="dxa" w:w="1440"/>
            <w:tcMar>
              <w:top w:type="dxa" w:w="60"/>
              <w:bottom w:type="dxa" w:w="60"/>
              <w:left w:type="dxa" w:w="100"/>
              <w:right w:type="dxa" w:w="100"/>
            </w:tcMar>
          </w:tcPr>
          <w:p>
            <w:pPr>
              <w:jc w:val="center"/>
            </w:pPr>
            <w:r>
              <w:rPr>
                <w:b/>
                <w:color w:val="1a6e3a"/>
                <w:sz w:val="16"/>
              </w:rPr>
              <w:t>\xe2\x80\x94</w:t>
            </w:r>
          </w:p>
        </w:tc>
        <w:tc>
          <w:tcPr>
            <w:tcW w:type="dxa" w:w="1500"/>
            <w:tcMar>
              <w:top w:type="dxa" w:w="60"/>
              <w:bottom w:type="dxa" w:w="60"/>
              <w:left w:type="dxa" w:w="100"/>
              <w:right w:type="dxa" w:w="100"/>
            </w:tcMar>
          </w:tcPr>
          <w:p>
            <w:pPr>
              <w:jc w:val="center"/>
            </w:pPr>
            <w:r>
              <w:rPr>
                <w:sz w:val="16"/>
              </w:rPr>
              <w:t>\xe2\x80\x94</w:t>
            </w:r>
          </w:p>
        </w:tc>
      </w:tr>\r\n""".replace(b"\n", b"\r\n")

# Insert before the avg row (which starts after W5 </w:tr>)
insert_point = 182060  # after W5 row end
content = content[:insert_point] + W6_IM_BENCH_ROW + content[insert_point:]
print(f"Inserted W6 bench row ({len(W6_IM_BENCH_ROW)} bytes)")

# Update avg row: 5 Windows -> 6 Windows, +94.3% -> +118.0%
content = content.replace(b'>5 Windows</w:t>', b'>6 Windows</w:t>', 1)
print("Updated 5 Windows -> 6 Windows in avg row")

with open(filepath, "wb") as f:
    f.write(content)
print(f"Saved {len(content)} bytes")
