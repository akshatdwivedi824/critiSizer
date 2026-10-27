from sqlalchemy import text

from critisizer.db import SessionLocal

with SessionLocal() as session:
    print(session.execute(text("select 1")).scalar())