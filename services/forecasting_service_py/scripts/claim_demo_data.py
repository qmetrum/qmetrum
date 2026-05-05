#!/usr/bin/env python3
"""Claim the demo data (owned by user_id=1) for a specific Cognito user.

When you sign up via Cognito for the first time, the backend creates a
fresh User row for you (e.g. user_id=2). The seeded demo data was created
under user_id=1 and is therefore invisible to you.

This script takes over user_id=1 by copying your Cognito sub onto that row
and removing the duplicate row Cognito auto-created. After running it, your
JWT will resolve to user_id=1 and you'll inherit all the demo portfolios,
watchlists, alerts, and saved screens.

Usage:
    python scripts/claim_demo_data.py --email amarkou@qmetrum.io
    python scripts/claim_demo_data.py --email amarkou@qmetrum.io --yes  # skip prompt
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from app.db.database import engine  # noqa: E402
from app.db.models import User  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Email of your Cognito-authenticated account")
    parser.add_argument("--demo-user-id", type=int, default=1, help="ID of the demo user to take over (default: 1)")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()

    target_email = args.email.strip().lower()

    with Session(engine) as session:
        # 1. Locate your Cognito-linked row
        user_with_sub = session.exec(
            select(User).where(User.email == target_email)
        ).first()
        if user_with_sub is None:
            print(f"ERROR: no user found with email={target_email}. Sign in via Cognito first.")
            return 1
        if not user_with_sub.cognito_sub:
            print(f"ERROR: user with email={target_email} has no cognito_sub. Sign in via Cognito at least once.")
            return 1

        cognito_sub = user_with_sub.cognito_sub
        cognito_name = user_with_sub.name

        # 2. Locate the demo user
        demo_user = session.exec(
            select(User).where(User.id == args.demo_user_id)
        ).first()
        if demo_user is None:
            print(f"ERROR: demo user with id={args.demo_user_id} not found.")
            return 1

        # Idempotent: if the demo user is already pointing at our cognito_sub, nothing to do
        if demo_user.cognito_sub == cognito_sub:
            print(
                f"OK: demo user (id={demo_user.id}) is already linked to {target_email}. "
                "Nothing to do."
            )
            return 0

        # 3. If the demo user already has a different cognito_sub, refuse
        if demo_user.cognito_sub and demo_user.cognito_sub != cognito_sub:
            print(
                f"ERROR: demo user (id={demo_user.id}) is already linked to a different "
                f"Cognito user (sub={demo_user.cognito_sub}). Aborting to avoid clobbering."
            )
            return 1

        same_user = user_with_sub.id == demo_user.id

        # 4. Show plan + confirm
        print("Plan:")
        print(f"  • User #{demo_user.id} (current email: {demo_user.email!r})")
        print(f"      → email = {target_email!r}")
        print(f"      → cognito_sub = {cognito_sub}")
        if cognito_name:
            print(f"      → name = {cognito_name!r}")
        if not same_user:
            print(f"  • Delete duplicate user #{user_with_sub.id} (auto-created by Cognito sign-in)")
        print()

        if not args.yes:
            ans = input("Proceed? [y/N] ").strip().lower()
            if ans not in ("y", "yes"):
                print("Aborted.")
                return 1

        # 5. Apply
        # If we're keeping demo_user and dropping user_with_sub, delete the
        # duplicate first so its unique constraints (email + cognito_sub)
        # are released before we update demo_user with the same values.
        if not same_user:
            session.delete(user_with_sub)
            session.flush()  # issue the DELETE before the UPDATE

        demo_user.email = target_email
        demo_user.cognito_sub = cognito_sub
        if cognito_name and not demo_user.name:
            demo_user.name = cognito_name
        demo_user.updated_at = datetime.utcnow()
        session.add(demo_user)

        session.commit()

    print(f"\n✓ Done. Sign out and back in — your JWT will now resolve to user_id={args.demo_user_id}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
