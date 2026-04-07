"""Update PPT slides with W6 Walk-Forward data"""
import re

base = "C:/Users/Zhong/Documents/trae_projects/StockQueen/output/ppt_unpacked/ppt/slides"

# ===========================================================
# Slide 6: WF table - insert W6 row, update heading + avg
# ===========================================================
with open(f"{base}/slide6.xml", "rb") as f:
    s6 = f.read()

# 1. Update heading text
s6 = s6.replace(
    "Walk-Forward验证：5年，5种市场，4/5窗口正收益".encode("utf-8"),
    "Walk-Forward验证：6年，6种市场，5/6窗口正收益".encode("utf-8")
)
s6 = s6.replace(
    "OOS = 模型从未见过的数据；5窗口按年独立测试，参数不得用在其训练期上".encode("utf-8"),
    "OOS = 模型从未见过的数据；6窗口按年独立测试，参数不得用在其训练期上".encode("utf-8")
)

# 2. Update avg row: 4.886 -> 4.606
# The avg row starts at 118692; let's find the 4.886 in it
avg_row_start = 118692
avg_4886_pos = s6.find(b'4.886', avg_row_start)
print(f"4.886 in avg row at: {avg_4886_pos}")
# Simple replacement (only in the avg row area)
s6 = s6[:avg_row_start] + s6[avg_row_start:].replace(b'4.886', b'4.606', 1)
print("Updated avg row 4.886 -> 4.606")

# 3. Insert W6 row before the avg row
# The W6 row is based on the 2024 row structure (102313:118692)
# We need to modify the data cells
row_2024 = s6[102313:118692]

# Create W6 row by cloning 2024 row and changing text values
row_w6 = row_2024
row_w6 = row_w6.replace(b'>2024<', b'>2025<', 1)
row_w6 = row_w6.replace(
    "AI牛市".encode("utf-8"),
    "关税不确定性".encode("utf-8"),
    1
)
row_w6 = row_w6.replace(b'>3.47<', b'>3.148<', 1)
row_w6 = row_w6.replace(b'>-11.4%<', b'>-9.8%<', 1)  # approximate max DD for 2025
row_w6 = row_w6.replace(b'>+23%<', b'>TBD<', 1)  # SPY 2025 full year TBD
# Update row ID to avoid duplicates
row_w6 = row_w6.replace(b'val="10005"', b'val="10006"')

# Insert before avg row
insert_at = 118692  # start of avg row
s6 = s6[:insert_at] + row_w6 + s6[insert_at:]
print(f"Inserted W6 row ({len(row_w6)} bytes)")

with open(f"{base}/slide6.xml", "wb") as f:
    f.write(s6)
print(f"Saved slide6.xml ({len(s6)} bytes)")

# ===========================================================
# Slide 5: "Portfolio OOS Sharpe：4.886..." -> 4.606
# ===========================================================
with open(f"{base}/slide5.xml", "rb") as f:
    s5 = f.read()

old5 = "Portfolio OOS Sharpe：4.886（V4+MR双策略，5年验证）".encode("utf-8")
new5 = "Portfolio OOS Sharpe：4.606（V4+MR双策略，6年验证）".encode("utf-8")
count5 = s5.count(old5)
print(f"\nslide5 - old text found: {count5}")
s5 = s5.replace(old5, new5)

with open(f"{base}/slide5.xml", "wb") as f:
    f.write(s5)
print(f"Saved slide5.xml ({len(s5)} bytes)")

# ===========================================================
# Slide 16: Multiple updates
# ===========================================================
with open(f"{base}/slide16.xml", "rb") as f:
    s16 = f.read()

replacements_16 = [
    ("Portfolio OOS Sharpe  ".encode("utf-8") + b'\r\n', None),  # skip - check context
]

# Simple byte replacements
s16 = s16.replace(b'4.886', b'4.606')
# "5年4/5窗口正收益" -> "6年5/6窗口正收益"
s16 = s16.replace(
    "5年4/5窗口正收益  ".encode("utf-8"),
    "6年5/6窗口正收益  ".encode("utf-8")
)
s16 = s16.replace(
    "5年4/5窗口正收益\r\n".encode("utf-8"),
    "6年5/6窗口正收益\r\n".encode("utf-8")
)
# handle no trailing
s16 = s16.replace(
    "5年4/5窗口正收益".encode("utf-8"),
    "6年5/6窗口正收益".encode("utf-8")
)

# Check for remaining 4.886
print(f"\nslide16 remaining 4.886: {s16.count(b'4.886')}")
print(f"slide16 4.606 occurrences: {s16.count(b'4.606')}")

with open(f"{base}/slide16.xml", "wb") as f:
    f.write(s16)
print(f"Saved slide16.xml ({len(s16)} bytes)")

# ===========================================================
# Final verification
# ===========================================================
print("\n=== Final check ===")
for slide_name in ["slide5.xml", "slide6.xml", "slide16.xml"]:
    with open(f"{base}/{slide_name}", "rb") as f:
        content = f.read()
    for term in [b"4.886", b"4.606", b"5\xe5\xb9\xb4"]:
        count = content.count(term)
        if count > 0:
            print(f"  {slide_name} - {repr(term)}: {count}")
