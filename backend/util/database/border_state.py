from .db_base import DatabaseBase


class BorderState(DatabaseBase):
    """Per output poster: its source's and its own (mtime, size) and the border settings at its last pass."""

    def get_all_map(self) -> dict:
        """Return {renamed_file: {source/output mtime and size, variant_sig}}."""
        rows = (
            self.execute_query(
                "SELECT renamed_file, source_mtime, source_size, output_mtime, "
                "output_size, variant_sig FROM border_state",
                fetch_all=True,
            )
            or []
        )
        return {
            r["renamed_file"]: {
                "source_mtime": r["source_mtime"],
                "source_size": r["source_size"],
                "output_mtime": r["output_mtime"],
                "output_size": r["output_size"],
                "variant_sig": r["variant_sig"],
            }
            for r in rows
        }

    def bulk_record(self, records: list, chunk_size: int = 500) -> int:
        """Upsert border_state rows (dicts keyed by its columns), one transaction per chunk."""
        sql = """
            INSERT INTO border_state
                (renamed_file, source_mtime, source_size, output_mtime,
                 output_size, variant_sig, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(renamed_file) DO UPDATE SET
                source_mtime=excluded.source_mtime,
                source_size=excluded.source_size,
                output_mtime=excluded.output_mtime,
                output_size=excluded.output_size,
                variant_sig=excluded.variant_sig,
                updated_at=excluded.updated_at
        """
        written = 0
        chunk: list = []
        for rec in records:
            chunk.append(
                (
                    sql,
                    (
                        rec["renamed_file"],
                        rec["source_mtime"],
                        rec["source_size"],
                        rec["output_mtime"],
                        rec["output_size"],
                        rec["variant_sig"],
                        rec["updated_at"],
                    ),
                )
            )
            if len(chunk) >= chunk_size:
                self.execute_transaction(chunk)
                written += len(chunk)
                chunk = []
        if chunk:
            self.execute_transaction(chunk)
            written += len(chunk)
        return written

    def clear(self) -> None:
        """Drop all rows (e.g. to force a full reprocess)."""
        self.execute_query("DELETE FROM border_state")
