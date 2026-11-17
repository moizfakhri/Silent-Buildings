"""Small local retrieval: BM25 and TF-IDF cosine over short texts (no network, no model download).

The IDF/length statistics are fitted once on a corpus sample; scoring then works on any list of documents (e.g. one building's
violation records) without refitting. Used for the RAG experiments, which must beat a plain SQL keyword baseline to be adopted.
"""
import re

import numpy as np
from sklearn.feature_extraction.text import CountVectorizer

TOKEN = re.compile(r"[a-z][a-z0-9]+")
STOP = {"the", "of", "and", "to", "in", "at", "or", "a", "an", "for", "is", "are", "with", "on", "by", "as", "that", "this", "it", "from", "be", "no", "not", "any"}


def tokens(text):
    return [t for t in TOKEN.findall(str(text).lower()) if t not in STOP]


class Bm25:
    def __init__(self, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.vec = CountVectorizer(analyzer=tokens)

    def fit(self, corpus):
        x = self.vec.fit_transform(corpus)
        df = np.asarray((x > 0).sum(axis=0)).ravel()
        n = x.shape[0]
        self.idf = np.log(1 + (n - df + 0.5) / (df + 0.5))
        self.avgdl = float(x.sum(axis=1).mean())
        return self

    def score(self, query, docs):
        q = self.vec.transform([query])
        idx = q.indices
        if not len(idx):
            return np.zeros(len(docs))
        x = self.vec.transform(docs).tocsc()
        dl = np.asarray(x.sum(axis=1)).ravel()
        out = np.zeros(len(docs))
        for j in idx:
            tf = x[:, j].toarray().ravel()
            out += self.idf[j] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return out

    def rank(self, query, docs, k=10):
        s = self.score(query, docs)
        return np.argsort(-s, kind="stable")[:k], s


class TfidfCosine:
    def __init__(self):
        self.vec = None

    def fit(self, corpus):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vec = TfidfVectorizer(analyzer=tokens, sublinear_tf=True).fit(corpus)
        return self

    def score(self, query, docs):
        q = self.vec.transform([query])
        x = self.vec.transform(docs)
        return np.asarray((x @ q.T).todense()).ravel()

    def rank(self, query, docs, k=10):
        s = self.score(query, docs)
        return np.argsort(-s, kind="stable")[:k], s


def sql_keyword_rank(keywords, docs, dates, k=10):
    """The plain-SQL baseline: ILIKE any keyword, newest first (what a SQL user would write)."""
    kw = [w.upper() for w in keywords]
    hit = np.array([any(w in str(d).upper() for w in kw) for d in docs])
    order = np.argsort([-(np.datetime64(d).astype("datetime64[D]").astype(int)) for d in dates], kind="stable")
    return [i for i in order if hit[i]][:k]
