"""Bounded lexical discovery. Matching is advice, never an authority decision."""
import re
import unicodedata


def normalize(text):
    return unicodedata.normalize('NFKC', text).casefold().replace('\u0451', '\u0435')


def terms(text):
    return list(dict.fromkeys(re.findall(r'\w+', normalize(text))))


def rank(query_terms, sections, title, aliases, mode='all'):
    normalized = [normalize(text) for _, text in sections]
    found = {term for term in query_terms if any(term in text for text in normalized)}
    if query_terms and (not found or (mode == 'all' and len(found) != len(query_terms))):
        return None
    heading = normalize(title)
    alias_text = normalize('\n'.join(aliases))
    score = sum(5 if term in heading else 4 if term in alias_text else 1 for term in found)
    index = max(range(len(sections)), key=lambda i: sum(term in normalized[i] for term in found))
    path, text = sections[index]
    # Find in original text to retain exact character coordinates despite Unicode
    # normalization expanding a character. Coordinates never address normalized text.
    words = list(re.finditer(r'\w+', text))
    position = next((word.start() for word in words if any(term in normalize(word.group()) for term in found)), 0)
    start = max(0, position - 120)
    end = min(len(text), start + 600)
    return {'score': score, 'matched_terms': sorted(found), 'matched_asset': path,
            'excerpt': text[start:end], 'fragment': {'unit':'unicode_characters', 'start':start,
                'end':end, 'section':'source_asset' if path else 'record_discovery_text'}}
