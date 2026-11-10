"""How much source text each policy has. Big prompts are slow on the local model."""

from sqlalchemy import text

from critisizer.db import SessionLocal

QUERY = """
select p.slug, count(*) as items, sum(length(i.excerpt)) as chars
from source_items i join policies p on p.id = i.policy_id
group by p.slug order by chars desc
"""

with SessionLocal() as session:
    for slug, items, chars in session.execute(text(QUERY)).all():
        print(f"{slug:36} items={items:3}  chars={chars:7}  ~tokens={chars // 4}")