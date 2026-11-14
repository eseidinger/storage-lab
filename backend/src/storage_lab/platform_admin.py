"""Grant the first metadata-backed platform administrator from the VM shell."""

import argparse

from .db import session_factory
from .models import PlatformAdmin, PlatformAdminEvent


def main() -> None:
    parser = argparse.ArgumentParser(description="Grant a Storage Lab platform administrator")
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--subject", required=True)
    args = parser.parse_args()
    if not args.issuer.strip() or not args.subject.strip() or "::" in args.issuer:
        parser.error("issuer and subject must be nonempty; issuer cannot contain '::'")
    identity = f"{args.issuer}::{args.subject}"
    with session_factory()() as session:
        if session.get(PlatformAdmin, identity) is None:
            session.add_all([
                PlatformAdmin(identity=identity, granted_by="bootstrap"),
                PlatformAdminEvent(actor="bootstrap", action="grant", identity=identity),
            ])
            session.commit()
            print(f"Granted platform-admin to {identity}")
        else:
            print(f"Already a platform-admin: {identity}")


if __name__ == "__main__":
    main()
