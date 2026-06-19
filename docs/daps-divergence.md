# CHUB — divergence from DAPS

CHUB is a fork of [DAPS](https://github.com/Drazzilb08/daps) by **Drazzilb08**. It
re-implements the DAPS modules (poster_renamerr, nohl, upgradinatorr, labelarr,
poster_cleanarr, and the rest) on a new database-backed, web-driven architecture —
and in doing so it fixes a number of upstream bugs.

This page documents the **behavioural divergences**: cases where CHUB does something
different from DAPS *and is more correct*. It exists so users migrating from DAPS know
what changes, and so anyone evaluating CHUB can see what the fork actually buys them.

> **Audited against:** DAPS `v2.0.3` (commit `9ea4bdf`, 26 Jul 2025). DAPS is actively
> developed; some of these may be fixed upstream in later versions. If you spot one that
> has, please open an issue so we can update this page.

**Legend:** 🔴 breaks a module in normal use · 🟠 wrong result or data loss in a real
scenario · 🟡 narrower edge case or robustness improvement.

---

## At a glance

Three DAPS modules are effectively broken or wrong in ordinary use, and are fixed in CHUB:

| Module | What goes wrong in DAPS | CHUB |
|---|---|---|
| **health_checkarr** | Every live (non-dry-run) prune crashes before deleting anything. Dry-run hides it. | Prunes correctly. |
| **nohl** | With the documented per-instance config shape, the *arr search phase crashes every run — no searches ever fire. | Searches fire. |
| **border_replacerr** | 3-digit hex colours (e.g. `#f0c`) are decoded to the wrong colour, so every poster gets the wrong border. | Correct colour. |

The rest of this page lists the divergences module by module.

---

## health_checkarr

🔴 **Live prune never works.** DAPS logs each deletion using a field that was never
populated, so the very first matched item raises an error and the run aborts before
deleting anything. The bug only appears in live mode — a dry-run looks fine — so it can
go unnoticed until you actually rely on it. CHUB prunes correctly and skips items with no
usable id instead of crashing.

---

## nohl (non-hardlinked media)

🔴 **No searches with per-instance config.** When instances are configured in the
documented per-instance form (e.g. `radarr_4k:` with its own settings), DAPS crashes
during the *arr-resolution step every run, so it never triggers any searches. Scan-only
setups don't hit it, which masks the problem. CHUB resolves instances correctly.

🟠 **Movies with extra folders are skipped.** DAPS decides "this is a TV series" if a
folder contains *any* sub-folder. A movie folder that happens to contain `Extras/`,
`Featurettes/`, `Subs/`, etc. is misread as a series, and its actual movie file is never
checked — so a non-hardlinked movie is silently missed. Conversely, a series that stores
episodes as loose files (no `Season NN/` folders) is mis-handled as a movie. CHUB keys on
real season folders and also handles loose `SxxExx` episode files.

🟠 **Search limit ignores seasons.** The "max searches per run" cap counts *shows*, not
search operations. One 12-season show with unlinked files counts as a single item, so a
limit of 5 can fire 60 season searches (and 60 deletes) in one run, hammering your
indexer. CHUB counts actual search operations.

## jduparr (hardlink repair)

🟠 **Miscounts duplicates and can falsely report success.** DAPS parses file paths out of
jdupes' human-readable summary text; duplicates that share a filename in different folders
get collapsed and undercounted, and a library path containing an apostrophe silently
breaks the whole command. It also ignores whether the relink step actually succeeded — if
linking fails (read-only mount, permissions), it still reports "items relinked" as if it
worked. CHUB reads jdupes' machine-readable JSON, checks the relink exit status, and
reports an error when linking fails.

---

## upgradinatorr

🟠 **Tags items even when the upgrade search failed.** DAPS applies the "checked" tag to
an item regardless of whether the search command actually succeeded. If a search times out
or fails, the item is still marked done — so it is **excluded from all future runs and
never retried**, a permanent silent gap in your upgrade coverage. CHUB only tags an item
once its search (every season, for series) completed successfully; failures are retried
next run.

🟡 **Misconfiguration safety.** A `count` of 0 (or missing) in DAPS unattended mode wipes
the "checked" tag from your entire library every scheduled run while tagging nothing. CHUB
skips the instance with a warning.

---

## renameinatorr

🟠 **Ignore-tag is bypassed once per cycle.** renameinatorr cycles a tag so each item is
processed once per pass. On the run that completes the cycle (all items tagged), DAPS
re-reads the whole library *without* re-applying your ignore filter — so every item you
tagged to be left alone gets renamed and re-tagged anyway, once per cycle. CHUB re-applies
the ignore filter after the cycle reset, so ignored items are never touched.

🟡 **Count throttle respected.** When an ignore/cycle tag is configured, DAPS effectively
ignores the per-run `count` limit and processes the whole untagged set at once. CHUB
honours the count throttle in this case too.

---

## labelarr (Plex labels ⇆ *arr tags)

🟠 **A label silently never syncs.** DAPS treats a tag whose internal id is `0` as
"not found". The first tag created in a fresh Radarr/Sonarr has id `0`, so that label is
dropped from the run entirely — never added to or removed from any Plex item. CHUB matches
labels by name, so id `0` is handled normally.

🟠 **Stale labels are never removed.** DAPS only updates labels on items it can still match
to *arr. If you remove a movie from Radarr (or its id changes), the label CHUB/DAPS added
to Plex is left behind forever. CHUB removes managed labels from Plex items that no longer
have a matching *arr entry.

🟡 **Per-library cache freshness.** CHUB reads Plex from a cached snapshot for speed. It
checks freshness **per library**, so a fresh "Movies" library can't mask a never-scanned
"Movies 4K" — which would otherwise get zero label syncs with no error.

---

## poster_cleanarr (removing orphaned poster assets)

This module deletes files, so its divergences are the highest-stakes.

🟠 **Deletes a poster when the folder name changes.** In its cleanup mode, DAPS matches an
asset to live media purely by folder name + year, with **no id fallback**. Rename a movie
in Radarr, correct its year, or add an edition tag, and the asset folder no longer matches
its own media — so DAPS deletes the poster even though the movie (same TMDB id) is plainly
still in your library. CHUB matches on the stable TMDB/TVDB id first, so an id that still
resolves is never deleted.

🟠 **No "keep the only copy" guard.** Combined with the above, when an asset folder's name
has drifted and it is the *only* poster for that media, DAPS removes it outright. CHUB
treats a wrong-named-but-id-matching folder as a stale duplicate and only removes it once
the correctly-named copy already exists on disk — so it self-heals instead of losing data.

🟠 **A partial *arr outage causes mass deletion.** DAPS compares assets against a live
*arr fetch. If one *arr is down (say Sonarr) while another is up, every asset belonging to
the unreachable instance matches nothing and is deleted. CHUB compares against its cached
media list and aborts entirely if the comparison set is empty, so a transient outage can't
trigger a purge. It also has a circuit-breaker that skips the sweep if most symlinked
assets look broken (a sign of an unmounted volume).

---

## unmatched_assets (reporting media missing a poster)

🟠 **In-library titles can be hidden from the report.** DAPS filters items by *arr status,
with no check for whether the file is actually present. A movie that's downloaded and in
Plex but still shows a not-yet-released status in Radarr (early/leaked release) is dropped
from the report — so you're never told its poster is missing. CHUB only applies the
release filter when the item is *not* in the library.

🟠 **A missing main poster can be overlooked.** For a show matched by title (no usable id),
DAPS only flags missing *season* posters; if every season has art but the show-level poster
is absent, it reports the show as complete. CHUB always flags a missing main poster.

---

## border_replacerr

🔴 **Wrong border colour for 3-digit hex.** A short hex colour like `#f0c` is expanded
incorrectly (`f0cf0c` instead of `ff00cc`), so the border is a completely different colour
than intended — on every poster. CHUB expands short hex the standard way.

🟠 **"Skip if unchanged" never works.** DAPS compares the new poster against the old using
a shallow check that's fooled by the file's modification time, so unchanged posters are
re-encoded and rewritten on every run — wasted CPU and disk churn, and it perturbs
mtime-based sync to Plex/Kometa. CHUB compares actual content and genuinely skips unchanged
posters.

🟡 **Leap-day holiday crash.** A holiday border schedule with a Feb 29 boundary date
crashes the whole border pass in non-leap years. CHUB clamps Feb 29 to Feb 28 and skips a
malformed holiday entry with a warning instead of aborting.

🟡 **Failures aren't hidden as successes.** A corrupt source image fails silently in DAPS
and is still counted toward "borders replaced". CHUB reports it as a failure and retries it
next run.

---

## sync_gdrive

🟠 **rclone argument injection.** DAPS passes your configured Drive folder id and
destination path straight to rclone. A value that begins with `-` is interpreted by rclone
as a command-line flag rather than a value, changing its behaviour unexpectedly. CHUB
rejects values that begin with `-` (and contain null bytes).

🟡 **Token shape handling.** Depending on how the Drive token is stored (a JSON string, the
`{}` redaction placeholder, or a structured object), DAPS can double-encode it and fail
auth. CHUB handles all three shapes.

🟡 **Conflicting credentials.** If both a service-account file and an OAuth token are
configured, DAPS passes both to rclone at once (ambiguous auth). CHUB uses one or the
other deterministically.

---

## Matching & title normalization (shared by all asset modules)

These affect how posters get matched to your media across every module.

🟠 **`{tvdbid-123}` blocks poison the title.** DAPS pulls the id out of a `{tvdbid-123}`
filename block but fails to strip the block itself, leaving garbage like `showtvdbid123` in
the normalized title — which then matches nothing. CHUB strips the whole block.

🟠 **Cross-source ids block a valid match.** DAPS refuses to fall back to title matching
whenever *both* sides carry *any* id — even when the ids are from different sources (a
TMDB-tagged poster vs a Sonarr item that only has a TVDB id), which is a common case. CHUB
only blocks the match when a *shared* id source actually disagrees.

🟠 **A whole match rule is dead.** Due to a key-name typo, DAPS's "match by folder title"
rule reads a field that's never set, so it never fires — a poster linked only by its folder
title is dropped as unmatched. CHUB reads the correct field.

🟡 **Smaller normalization gaps.** Region tags in mixed case (`(us)` vs `(US)`), `&` vs
`and`, and certain season-tag forms aren't normalized consistently in DAPS, causing
near-miss titles to fail to match. CHUB normalizes all of these.

---

## Known CHUB limitation

In the interest of honesty: CHUB's release-readiness filter (the fix for the
unmatched_assets issue above) still has one narrow edge. For legacy database rows that
predate the `has_content` column and haven't been refreshed by an *arr sync since, an item
whose *arr status is a stale unreleased value can still be wrongly excluded from the
unmatched report. This is much narrower than the DAPS bug it replaces (it only affects
un-resynced legacy rows) and is closed by running an *arr sync. It's tracked for a proper
fix.

---

*With thanks to **Drazzilb08** and the DAPS project — the scripts and inspiration that made
CHUB possible. None of the above is a criticism of DAPS; bugs are inevitable in any active
project, and this page simply records where the fork has diverged.*
