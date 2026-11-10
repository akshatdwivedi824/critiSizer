"""Delete undecided AI drafts from the dev database. Never touches approved or rejected."""

from sqlalchemy import text

from critisizer.db import SessionLocal

with SessionLocal() as session:
    result = session.execute(text("DELETE FROM indicators WHERE status = 'ai_draft'"))
    session.commit()
    print("deleted", result.rowcount)