import html
import os
import re
import unicodedata

from unidecode import unidecode

from backend.util.constants import (
    common_words,
    id_content_regex,
    illegal_chars_regex,
    remove_special_chars,
    season_number_regex,
    words_to_remove,
    year_regex,
)

# Compiled once: case-insensitive match for any token in words_to_remove.
# Replaces a previous str.replace loop that was case-sensitive and missed
# lowercase region tags like "(us)" or "(uk)".
_tokens_regex = re.compile(
    "|".join(re.escape(t) for t in words_to_remove), re.IGNORECASE
)

# Zero-width and bidi/format control chars (ZWSP/ZWNJ/ZWJ, LRM/RLM, BOM)
# that occasionally appear in curator-exported filenames and would
# otherwise survive normalization. NBSP (U+00A0) is handled separately so
# it converts to a real space rather than gluing adjacent words.
_invisible_chars_regex = re.compile("[\u200B-\u200F\uFEFF]")

# Combining diacritical marks left over after NFD decomposition.
_combining_marks_regex = re.compile("[\u0300-\u036f]")

# Emoji ranges covering pictographs, symbols, flags, and dingbats.
_emoji_regex = re.compile(
    "["
    "\U0001f600-\U0001f64f"
    "\U0001f300-\U0001f5ff"
    "\U0001f680-\U0001f6ff"
    "\U0001f700-\U0001f77f"
    "\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "\U00002700-\U000027bf"
    "\U0001f1e0-\U0001f1ff"
    "]+",
    flags=re.UNICODE,
)


def _clean_unicode(text: str) -> str:
    """Strip zero-width chars, normalize en/em dashes, drop combining marks
    left by NFD decomposition, and strip emoji. Defense-in-depth on top of
    unidecode for inputs unidecode can't fully transliterate.
    """
    text = text.replace("\u00a0", " ")
    text = _invisible_chars_regex.sub("", text)
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = unicodedata.normalize("NFD", text)
    text = _combining_marks_regex.sub("", text)
    text = _emoji_regex.sub("", text)
    return text


def remove_common_words(text: str) -> str:
    """Remove complete words found in common_words (case-insensitive).

    Args:
        text (str): Input text.

    Returns:
        str: Text with common words removed.
    """
    words = text.split()
    filtered = [
        word for word in words if word.lower() not in {w.lower() for w in common_words}
    ]
    return " ".join(filtered)


def remove_tokens(text: str) -> str:
    """Remove specified unwanted substrings from text (case-insensitive).

    Args:
        text (str): Input text.

    Returns:
        str: Text with tokens removed.
    """
    return _tokens_regex.sub("", text)


def normalize_file_names(file_name: str) -> str:
    """Normalize filename for indexing.

    Steps:
      1. Strip extension.
      2. Convert HTML entities and unicode to ASCII.
      3. Remove ID tokens in curly braces.
      4. Remove specified unwanted substrings.
      5. Remove illegal filename characters.
      6. Remove miscellaneous special symbols.
      7. Remove common filler words.
      8. Remove whitespace and lowercase.

    Args:
        file_name (str): Filename to normalize.

    Returns:
        str: Normalized filename.
    """
    base, _ = os.path.splitext(file_name)
    cleaned = _clean_unicode(html.unescape(base))
    cleaned = unidecode(cleaned)
    cleaned = cleaned.replace("&", " and ")
    cleaned = id_content_regex.sub("", cleaned)
    cleaned = remove_tokens(cleaned)
    cleaned = illegal_chars_regex.sub("", cleaned)
    cleaned = re.sub(remove_special_chars, "", cleaned)
    cleaned = remove_common_words(cleaned)
    cleaned = cleaned.replace(" ", "").lower()
    return cleaned.strip()


def parse_asset_filename(file_name: str) -> str:
    """Strip extension, ID blocks, year, and season tags from an asset filename
    to yield the bare title used for media matching.

    Mirrors the inline triplet historically used by poster_renamerr's
    `_get_assets_files()` so callers needing the same key share one source.
    """
    base, _ = os.path.splitext(file_name)
    base = _clean_unicode(html.unescape(base))
    base = id_content_regex.sub("", base).strip()
    base = year_regex.sub("", base).strip()
    base = season_number_regex.sub("", base).strip(" -_")
    return base


def normalize_titles(title: str) -> str:
    """Normalize media title for matching and indexing.

    Steps:
      1. Strip year tag.
      2. Convert HTML entities and unicode to ASCII.
      3. Remove ID tokens in curly braces.
      4. Remove specified unwanted substrings.
      5. Remove illegal filename characters.
      6. Remove miscellaneous special symbols.
      7. Remove whitespace and lowercase.

    Args:
        title (str): Media title to normalize.

    Returns:
        str: Normalized title.
    """
    normalized_title = year_regex.sub("", title)
    normalized_title = _clean_unicode(html.unescape(normalized_title))
    normalized_title = unidecode(normalized_title).strip()
    normalized_title = normalized_title.replace("&", " and ")
    normalized_title = id_content_regex.sub("", normalized_title)
    normalized_title = remove_tokens(normalized_title)
    normalized_title = illegal_chars_regex.sub("", normalized_title)
    normalized_title = re.sub(remove_special_chars, "", normalized_title)
    normalized_title = normalized_title.replace(" ", "").lower()
    return normalized_title.strip()
