#!/usr/bin/env python3
"""
Test script to check lark-oapi SDK version and import structure
"""

import lark_oapi as lark

print("Lark SDK version:", lark.__version__)
print("Available modules:", dir(lark))

# Check for EventDispatcher
print("\nChecking for EventDispatcher...")
try:
    from lark_oapi import event
    print("event module available:", dir(event))
    
    from lark_oapi.event import dispatcher
    print("dispatcher module available:", dir(dispatcher))
    
    EventDispatcher = dispatcher.EventDispatcher
    print("EventDispatcher found")
except Exception as e:
    print("Error finding EventDispatcher:", e)

# Check for P2ImMessageReceiveV1
try:
    from lark_oapi.service.im.v1 import P2ImMessageReceiveV1
    print("P2ImMessageReceiveV1 found")
except Exception as e:
    print("Error finding P2ImMessageReceiveV1:", e)
