"""Small, deterministic Unicode ranking for eligible SQLite memory records.

This is a linear scan, not a vector index. Only the top k matches are retained.
Search normalization is separate from lifecycle hashes so upgrades cannot
change the identity of a stored or suppressed memory.
"""

from __future__ import annotations

import heapq
import re
import unicodedata

HAN = re.compile(r"[\u3400-\u9fff]+")
WORDS = re.compile(r"[^\W_]+", re.UNICODE)
STOP = {"the", "a", "an", "and", "or", "is", "are", "was", "were", "to", "of", "in", "on", "at", "my", "me", "i", "it", "its", "his", "her", "he", "she", "they", "their", "we", "our", "you", "your", "about", "what", "when", "where", "how", "please", "tell", "does", "do", "did", "can", "could", "would", "for", "with", "this", "that", "which", "remember", "know"}
HAN_STOP = ("请问", "什么", "怎么", "如何", "告诉", "一下", "的", "了", "吗", "呢", "是", "我", "你", "他", "她", "们")
REVISION_WORDS = {"corrected", "updated", "revised"}


def normalize(text):
    value = unicodedata.normalize("NFKC", text).casefold()
    # FTS's unicode61 strips Latin accents. Keep that useful behavior here.
    value = "".join(c for c in unicodedata.normalize("NFD", value) if not unicodedata.combining(c))
    return " ".join(value.split())


def terms(text):
    value = normalize(text)
    han = []
    for run in HAN.findall(value):
        for stop in HAN_STOP:
            run = run.replace(stop, " ")
        han.extend(piece for piece in run.split() if len(piece) >= 2)
    words = [w for w in WORDS.findall(HAN.sub(" ", value)) if w not in STOP and len(w) >= 2]
    # Revision qualifiers ask for the active value; they need not occur in the
    # value itself. Keep a qualifier-only query searchable, never match all rows.
    substantive = [w for w in words if w not in REVISION_WORDS]
    if substantive or han:
        words = substantive
    return list(dict.fromkeys(words))[:16], list(dict.fromkeys(han))[:16]


def word_forms(word):
    """Match a few English inflections without substring or synonym expansion."""
    forms = {word}
    if word.isascii() and word.isalpha():
        if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
            forms.add(word[:-1])
        for form in tuple(forms):
            if len(form) >= 6 and form.endswith("ing"):
                forms.add(form[:-3])
    return forms


def relevance(query_terms, text):
    words, han = query_terms
    if not words and not han:
        return 0.0
    value = normalize(text)
    available = {form for word in WORDS.findall(HAN.sub(" ", value)) for form in word_forms(word)}
    hits = sum(bool(word_forms(w) & available) for w in words)
    for run in han:
        if run in value:
            hits += 1
        elif len(run) > 2:
            grams = {run[i:i + 2] for i in range(len(run) - 1)}
            coverage = sum(g in value for g in grams) / len(grams)
            if coverage >= 0.6:
                hits += coverage
    coverage = hits / (len(words) + len(han))
    return coverage if coverage >= 0.6 else 0.0


def search(conn, policy, query, kind, k):
    query_terms = terms(query[:256])
    if not any(query_terms):
        return []
    table, column = ("facts", "content") if kind == "fact" else ("episodes", "summary")
    visible, args = policy.visible_sql()
    # Filtering precedes ranking and LIMIT. No recent-N candidate shortcut can
    # hide an older, more relevant fact or admit another session's data.
    rows = conn.execute(f"SELECT * FROM {table} WHERE {visible}", args)

    def candidates():
        for row in rows:
            item = dict(row)
            text = item[column]
            score = relevance(query_terms, item.get("subject", "") + " " + text)
            if not score or policy.clean_text(text) != text:
                continue
            item.update(kind=kind, text=text, rank=score)
            yield item

    def order(item):
        return (item["rank"], {"correction": 3, "user": 2, "consolidation": 1}.get(item.get("source"), 0),
                item.get("updated_at") or item.get("happened_at") or item.get("created_at") or "", item["id"])

    return heapq.nlargest(k, candidates(), key=order)
