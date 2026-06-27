# backend/extensions/poster_self_heal/__init__.py
"""Poster Self-Heal — develop-only extension.

Keeps the user's CL2K poster drive current: re-resolves each generated poster
against TMDB and proposes rewriting a stale embedded id, a changed title, or a
missing id. Proposals are applied only after manual review (rclone moveto on the
user's Drive via cl2k.gdrive_upload, os.replace for the local source copy).

Operates on the CL2K maker's own output: it reads ``cl2k_maker.output_dir`` and
``cl2k_maker.gdrive_folder_id`` from the loaded config rather than defining its
own source.
"""
