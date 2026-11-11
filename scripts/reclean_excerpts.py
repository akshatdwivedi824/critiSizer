"""Apply the text_v2 cleaning rules to excerpts already stored.

Dry run by default. --apply writes the cleaned text. --prune-empty also deletes
rows left with no body text, but never one that an evidence row cites.
"""

import argparse
import hashlib

from sqlalchemy import select

from critisizer.db import SessionLocal
from critisizer.evidence.text import clean_paragraph
from critisizer.models import Evidence, SourceItem


def cleaned(excerpt: str) -> tuple[str, str]:
    """(new excerpt, new body)."""
    title, _, body = excerpt.partition("\n")
    kept = "\n".join(c for line in body.split("\n") if (c := clean_paragraph(line)))
    return f"{title}\n{kept}", kept


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--prune-empty", action="store_true")
    args = parser.parse_args()
    changed = clashes = pruned = kept_cited = 0
    with SessionLocal() as session:
        for item in session.scalars(select(SourceItem).order_by(SourceItem.id)):
            new, body = cleaned(item.excerpt)
            if not body.strip():
                cited = session.scalar(
                    select(Evidence.id).where(Evidence.source_item_id == item.id)
                )
                if cited:
                    kept_cited += 1
                    print(f"#{item.id} {item.outlet}: no body text but cited, kept")
                elif args.prune_empty:
                    pruned += 1
                    print(f"#{item.id} {item.outlet}: no body text, delete")
                    if args.apply:
                        session.delete(item)
                    continue
                else:
                    print(f"#{item.id} {item.outlet}: no body text (use --prune-empty)")
            if new == item.excerpt:
                continue
            new_hash = hashlib.sha256(new.encode("utf-8")).hexdigest()
            clash = session.scalar(
                select(SourceItem.id).where(
                    SourceItem.policy_id == item.policy_id,
                    SourceItem.content_hash == new_hash,
                    SourceItem.id != item.id,
                )
            )
            if clash:
                clashes += 1
                print(f"skip #{item.id}: cleaned text equals #{clash}")
                continue
            changed += 1
            print(f"#{item.id} {item.outlet}: {len(item.excerpt)} -> {len(new)} chars")
            if args.apply:
                item.excerpt = new
                item.content_hash = new_hash
        if args.apply:
            session.commit()
    mode = "applied" if args.apply else "dry run"
    print(
        f"[{mode}] {changed} cleaned, {pruned} empty deleted, "
        f"{kept_cited} empty but cited, {clashes} skipped"
    )


if __name__ == "__main__":
    main()