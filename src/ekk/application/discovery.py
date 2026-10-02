"""Bounded lexical discovery. Matching is advice, never an authority decision."""
import collections
import functools
import math
from pathlib import PurePosixPath
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


# Work-entry relevance. Scores only order optional reading; the caller keeps
# selection authority, mandatory reading and access decisions.

ENTRY_SOURCE_LEAD_CHARS = 8192
ENTRY_RELATIVE_SCORE_FLOOR = 0.25
# Multiplier on the plain score of imported and not-adopted history. Like
# RecordRanker.PREFERENCE_BOOST it is an unmeasured prior, applied by the entry
# and judged by the owner's relevance sample.
ARCHIVE_PRIOR = 0.5
TEXT_ASSET_SUFFIXES = frozenset({'.md', '.txt', '.csv', '.tsv', '.json', '.yaml', '.yml', '.html', '.xml'})
_STOP_WORDS = frozenset('''
a about above after again against all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each else few for from further had has have
having he her here hers him his how however i if in into is it its itself just let me more most my no nor
not now of off on once only or other our ours out over own same she should so some such than that the
their theirs them then there these they this those through to too under until up upon us very via was we
were what when where which while who whom why will with within without would yet you your yours
http https www com org html htm md
\u0430 \u0431\u0435\u0437 \u0431\u043e\u043b\u0435\u0435 \u0431\u044b \u0431\u044b\u043b \u0431\u044b\u043b\u0430 \u0431\u044b\u043b\u0438 \u0431\u044b\u043b\u043e \u0431\u044b\u0442\u044c \u0432 \u0432\u0430\u043c \u0432\u0430\u0441 \u0432\u0435\u0441\u044c \u0432\u043e \u0432\u043e\u0442 \u0432\u0441\u0435 \u0432\u0441\u0435\u0433\u043e \u0432\u0441\u0435\u0445 \u0432\u044b \u0433\u0434\u0435 \u0434\u0430 \u0434\u0430\u0436\u0435 \u0434\u043b\u044f \u0434\u043e \u0435\u0433\u043e
\u0435\u0435 \u0435\u0439 \u0435\u0441\u043b\u0438 \u0435\u0441\u0442\u044c \u0435\u0449\u0435 \u0436 \u0436\u0435 \u0437\u0430 \u0437\u0434\u0435\u0441\u044c \u0438 \u0438\u0437 \u0438\u043b\u0438 \u0438\u043c \u0438\u0445 \u043a \u043a\u0430\u043a \u043a\u043e \u043a\u043e\u0433\u0434\u0430 \u043a\u0442\u043e \u043b\u0438 \u043b\u0438\u0431\u043e \u043c\u043d\u0435 \u043c\u043e\u0436\u0435\u0442 \u043c\u044b \u043d\u0430 \u043d\u0430\u0434 \u043d\u0430\u043c \u043d\u0430\u0441 \u043d\u0435
\u043d\u0435\u0433\u043e \u043d\u0435\u0435 \u043d\u0435\u0442 \u043d\u0438 \u043d\u0438\u0445 \u043d\u043e \u043d\u0443 \u043e \u043e\u0431 \u043e\u0434\u043d\u0430\u043a\u043e \u043e\u043d \u043e\u043d\u0430 \u043e\u043d\u0438 \u043e\u043d\u043e \u043e\u0442 \u043f\u043e \u043f\u043e\u0434 \u043f\u0440\u0438 \u043f\u0440\u043e \u0441 \u0441\u043e \u0442\u0430\u043a \u0442\u0430\u043a\u0436\u0435 \u0442\u0430\u043a\u043e\u0439 \u0442\u0430\u043c \u0442\u0435 \u0442\u0435\u043c \u0442\u043e
\u0442\u043e\u0433\u043e \u0442\u043e\u0436\u0435 \u0442\u043e\u0439 \u0442\u043e\u043b\u044c\u043a\u043e \u0442\u043e\u043c \u0442\u044b \u0443 \u0443\u0436\u0435 \u0445\u043e\u0442\u044f \u0447\u0435\u0433\u043e \u0447\u0435\u0439 \u0447\u0435\u043c \u0447\u0442\u043e \u0447\u0442\u043e\u0431\u044b \u0447\u044c\u0435 \u0447\u044c\u044f \u044d\u0442\u0430 \u044d\u0442\u0438 \u044d\u0442\u043e \u044d\u0442\u043e\u0442 \u044f
'''.split())
_RU_ENDINGS = tuple(sorted('''\u0438\u044f\u043c\u0438 \u044f\u043c\u0438 \u0430\u043c\u0438 \u043e\u0433\u043e \u0435\u0433\u043e \u043e\u043c\u0443 \u0435\u043c\u0443 \u044b\u043c\u0438 \u0438\u043c\u0438 \u0438\u0435\u0439 \u0438\u044f\u0445 \u0430\u0445 \u044f\u0445 \u043e\u0432 \u0435\u0432 \u0435\u0439 \u043e\u0439 \u0438\u0439 \u044b\u0439 \u0430\u044f \u044f\u044f \u043e\u0435 \u0435\u0435
\u044b\u0435 \u0438\u0435 \u0443\u044e \u044e\u044e \u043e\u043c \u0435\u043c \u0430\u043c \u044f\u043c \u0438\u044e \u0438\u044f \u0438\u0438 \u044c\u044e \u044b \u0438 \u0430 \u044f \u043e \u0435 \u0443 \u044e \u044c'''.split(), key=len, reverse=True))
_MARKUP = re.compile(r'<(script|style)\b.*?</\1\s*>|<[^>]{0,2000}>', re.S | re.I)
_ENTITY = re.compile(r'&#?\w{1,10};')


@functools.lru_cache(maxsize=262144)
def stem(term):
    """Conservative suffix stripping so inflected forms of one word match."""
    if len(term) >= 5 and not term.isascii():
        for ending in _RU_ENDINGS:
            if term.endswith(ending) and len(term) - len(ending) >= 4:
                return term[:-len(ending)]
        return term
    if len(term) >= 5 and term.isascii() and term.isalpha():
        if term.endswith('ies') and len(term) > 5:
            return term[:-3] + 'y'
        if term.endswith('ing') and len(term) > 6:
            return term[:-3]
        if term.endswith(('ed', 'es')) and len(term) > 5:
            return term[:-2]
        if term.endswith('s') and not term.endswith('ss'):
            return term[:-1]
    return term


def content_terms(text):
    """Normalized meaningful words: no stop words, single letters or short numbers."""
    return [stem(word) for word in re.findall(r'\w+', normalize(text))
            if len(word) > 1 and word not in _STOP_WORDS and not (word.isdigit() and len(word) < 3)]


def source_lead(path, raw, limit=ENTRY_SOURCE_LEAD_CHARS):
    """Readable opening of a text asset with markup removed; None for other assets."""
    suffix = PurePosixPath(path).suffix.lower()
    if suffix not in TEXT_ASSET_SUFFIXES:
        return None
    text = raw[:limit * 8].decode('utf-8', errors='ignore')
    if suffix in {'.html', '.xml'} or text.lstrip().startswith('<'):
        text = _ENTITY.sub(' ', _MARKUP.sub(' ', text))
    return ' '.join(text.split())[:limit]


class RecordRanker:
    """BM25 relevance of records to a task over title, aliases, body and source leads.

    An optional query_weight(stem) in (0, 1] scales each task word, so words common
    to many tasks count for less. Scores are plain: priors such as PREFERENCE_BOOST
    are applied by the caller that orders an entry, never here.

    Common words weigh little (inverse document frequency), and a long document
    does not outrank a focused one merely by containing more words (length
    normalization). The opening of each text asset is read, never a whole
    capture, so ranking cost does not grow with archived page size.
    """
    WEIGHTS = {'title': 3.0, 'aliases': 3.0, 'body': 1.0, 'source': 1.0}
    PREFERENCE_BOOST = 1.5  # unmeasured prior for an owner's stated preference; see ARCHIVE_PRIOR

    def __init__(self, records, files, *, lead_chars=ENTRY_SOURCE_LEAD_CHARS, k1=1.2, b=0.75, query_weight=None):
        self._records, self._files, self._lead, self._k1, self._b = records, files, lead_chars, k1, b
        self._query_weight = query_weight
        self.coverage = {'method': 'bm25', 'field_weights': dict(self.WEIGHTS), 'source_lead_chars': lead_chars,
                         'scanned_chars': 0, 'partial_assets': 0, 'unsearchable_assets': 0, 'duplicate_leads': 0,
                         'query_weights_applied': False}
        self._terms, self._length = {}, {}
        frequency = collections.Counter()
        for key, row in records.items():
            counts, length = collections.Counter(), 0.0
            for field, text in self._sections(row, account=True):
                words = content_terms(text)
                weight = self.WEIGHTS[field.split(':', 1)[0]]
                for word in words:
                    counts[word] += weight
                length += weight * len(words)
            self._terms[key], self._length[key] = counts, max(length, 1.0)
            frequency.update(counts.keys())
        self._frequency, self._count = frequency, len(records)
        self._average = sum(self._length.values()) / max(self._count, 1)

    def _sections(self, row, *, account=False):
        metadata = row['metadata']
        yield 'title', metadata.get('title') or ''
        yield 'aliases', ' '.join(metadata.get('aliases', []))
        yield 'body', row.get('body') or ''
        body = None
        for asset in metadata.get('source', {}).get('assets', []):
            raw = self._files.get(asset.get('path'))
            lead = None if raw is None else source_lead(asset['path'], raw, self._lead)
            if lead:
                # An imported document whose record body is its own asset text
                # would otherwise count every word twice.
                if body is None:
                    body = ' '.join((row.get('body') or '').split())
                if lead == body[:self._lead]:
                    if account:
                        self.coverage['duplicate_leads'] += 1
                    continue
            if account:
                if lead is None:
                    self.coverage['unsearchable_assets'] += 1
                else:
                    self.coverage['scanned_chars'] += len(lead)
                    self.coverage['partial_assets'] += len(raw) > self._lead
            if lead:
                yield 'source:' + asset['path'], lead

    def _weights(self, query):
        """Weight in (0, 1] per query stem; a value outside that range counts as 1."""
        if self._query_weight is None:
            return dict.fromkeys(query, 1.0)
        weights = {}
        for term in query:
            value = self._query_weight(term)
            weights[term] = float(value) if isinstance(value, (int, float)) and 0 < value <= 1 else 1.0
        return weights

    def _idf(self, term):
        seen = self._frequency.get(term, 0)
        return math.log(1 + (self._count - seen + 0.5) / (seen + 0.5))

    def scores(self, task):
        """Positive BM25 score per record key; records sharing no content word are absent."""
        query = set(content_terms(task))
        weights = self._weights(query)
        self.coverage['query_weights_applied'] = any(value != 1.0 for value in weights.values())
        idf = {term: weights[term] * self._idf(term) for term in query}
        result = {}
        for key, counts in self._terms.items():
            norm = self._k1 * (1 - self._b + self._b * self._length[key] / self._average)
            score = sum(idf[term] * counts[term] * (self._k1 + 1) / (counts[term] + norm)
                        for term in query if term in counts)
            if score > 0:
                result[key] = score
        return result

    def explain(self, key, task, *, width=280):
        """Matched task words and the passage where they concentrate, for display only."""
        query = set(content_terms(task))
        matched, best, opening = set(), None, None
        for field, text in self._sections(self._records[key]):
            hits = [(word.start(), stem(normalize(word.group()))) for word in re.finditer(r'\w+', text)]
            hits = [(position, term) for position, term in hits if term in query]
            matched.update(term for _, term in hits)
            if field in ('title', 'aliases'):
                continue
            if opening is None and text.strip():
                opening = (field, text.strip()[:width])
            for index, (position, _) in enumerate(hits):
                distinct = len({term for at, term in hits[index:] if at < position + width})
                if best is None or distinct > best[0]:
                    best = (distinct, field, text, position)
        if best:
            _, section, text, position = best
            start = max(0, position - 60)
            boundary = text.rfind(' ', max(0, start - 40), start)
            start = boundary + 1 if boundary >= 0 else start
            excerpt = text[start:start + width].strip()
        else:
            section, excerpt = opening or (None, None)
        # The most informative matched words first, so a short reason names the topic.
        weights = self._weights(matched)
        words = sorted({word for word in re.findall(r'\w+', normalize(task)) if stem(word) in matched},
                       key=lambda word: (-weights[stem(word)] * self._idf(stem(word)), word))
        return {'matched_terms': words[:6], 'excerpt': excerpt, 'section': section}
