"""Add W6 row to benchmark comparison table in DataPack"""
filepath = "C:/Users/Zhong/Documents/trae_projects/StockQueen/output/datapack_unpacked/word/document.xml"
with open(filepath, "rb") as f:
    content = f.read()

W6_BENCH_ROW = b"""      <w:tr>
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

# Find the end of W5 row in benchmark table
# W5 row ends with </w:tr> right before <w:tr> with E8F4E8 shading (avg row)
marker = b'      </w:tr>\r\n      <w:tr>\r\n        <w:trPr>\r\n          <w:shd w:fill="E8F4E8"'
idx = content.find(marker)
print(f"Found avg row marker at: {idx}")
if idx > 0:
    insertion_point = idx + len(b"      </w:tr>\r\n")
    new_content = content[:insertion_point] + W6_BENCH_ROW + content[insertion_point:]
    with open(filepath, "wb") as f:
        f.write(new_content)
    print(f"Saved {len(new_content)} bytes")
else:
    print("ERROR: marker not found")
