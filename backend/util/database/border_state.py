from .db_base import DatabaseBase


class BorderState(DatabaseBase):
    """Interface for the border_state table.

    Tracks, per output poster, the (mtime, size) of the file border_replacerr
    last wrote and a signature of the border settings used. On the next run
    a poster is skipped entirely (no decode/resize/encode) when its output
    file is unchanged AND the signature it would be processed with matches —
    i.e. the result would be byte-identical to what's already on disk.

    Keying on the OUTPUT file (not the source) makes this robust whether the
    border is applied in place or to a separate path: any upstream re-upload
    that replaces the poster bumps its mtime/size and invalidates the gate.
    """

    def get_all_map(self) -> dict:
        """Return {renamed_file: {source_mtime, source_size, variant_sig}}."""
        rows = (
            self.execute_query(
                "SELECT renamed_file, source_mtime, source_size, variant_sig "
                "FROM border_state",
                fetch_all=True,
            )
            or []
        )
        return {
            r["renamed_file"]: {
                "source_mtime": r["source_mtime"],
                "source_size": r["source_size"],
                "variant_sig": r["variant_sig"],
            }
            for r in rows
        }

    def bulk_record(self, records: list, chunk_size: int = 500) -> int:
        """Upsert many border-state rows, one transaction per chunk.

        records: dicts with renamed_file, source_mtime, source_size,
        variant_sig, updated_at.
        """
        sql = """
            INSERT INTO border_state
                (renamed_file, source_mtime, source_size, variant_sig, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(renamed_file) DO UPDATE SET
                source_mtime=excluded.source_mtime,
                source_size=excluded.source_size,
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
