"""
Create admin users in Supabase Auth.

Run once to set up the two admin accounts:
  python scripts/create_admin_users.py

You'll be prompted for emails and passwords.
Requires SUPABASE_URL and SUPABASE_SERVICE_KEY in .env.
"""

import os
import sys
import getpass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")

    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        sys.exit(1)

    db = create_client(url, key)

    print("=== StockQueen Admin User Setup ===\n")

    users = []
    for i in range(1, 3):
        print(f"--- User {i} ---")
        email = input(f"  Email: ").strip()
        password = getpass.getpass(f"  Password (min 6 chars): ")

        if len(password) < 6:
            print("  ERROR: Password must be at least 6 characters")
            sys.exit(1)

        users.append({"email": email, "password": password})

    print("\nCreating users...")
    for u in users:
        try:
            result = db.auth.admin.create_user({
                "email": u["email"],
                "password": u["password"],
                "email_confirm": True,  # Skip email verification
            })
            print(f"  Created: {u['email']} (id: {result.user.id})")
        except Exception as e:
            error_str = str(e)
            if "already been registered" in error_str or "already exists" in error_str:
                print(f"  Already exists: {u['email']} (skipping)")
            else:
                print(f"  ERROR creating {u['email']}: {e}")

    print("\nDone! Users can now login at /login")


if __name__ == "__main__":
    main()
