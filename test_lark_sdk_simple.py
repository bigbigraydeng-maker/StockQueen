#!/usr/bin/env python3
"""
Simple test for lark-oapi SDK structure
"""

import lark_oapi

print("Lark SDK modules:", dir(lark_oapi))

# Check available submodules
print("\nChecking submodules...")
try:
    import lark_oapi.core
    print("core module:", dir(lark_oapi.core))
except Exception as e:
    print("core module error:", e)

try:
    import lark_oapi.ws
    print("ws module:", dir(lark_oapi.ws))
except Exception as e:
    print("ws module error:", e)

try:
    import lark_oapi.event
    print("event module:", dir(lark_oapi.event))
except Exception as e:
    print("event module error:", e)
