from dataclasses import dataclass
from typing import List, Optional, Dict

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class TFIDFDocument:
    text: str
    chunk_id: Optional[str] = None
    contract_id: Optional[str] = None


class TFIDFRetriever:

    def __init__(self):
        self.vectorizer = TfidfVectorizer(
            lowercase=True,
            stop_words="english",
            ngram_range=(1, 2),
            max_df=0.95,
            min_df=1,
        )

        self.documents: List[TFIDFDocument] = []
        self.matrix = None

    def fit(self, documents: List[TFIDFDocument]):
        """Build the TF-IDF index."""

        if not documents:
            return

        self.documents = documents

        texts = [doc.text for doc in documents]

        self.matrix = self.vectorizer.fit_transform(texts)

    def search(
        self,
        query: str,
        top_k: int = 5
    ) -> List[Dict]:

        if self.matrix is None:
            return []

        query_vector = self.vectorizer.transform([query])

        similarities = cosine_similarity(
            query_vector,
            self.matrix
        )[0]

        top_indices = np.argsort(
            similarities
        )[::-1][:top_k]

        results = []

        for idx in top_indices:

            score = float(similarities[idx])

            if score <= 0:
                continue

            document = self.documents[idx]

            results.append({
                "text": document.text,
                "chunk_id": document.chunk_id,
                "contract_id": document.contract_id,
                "score": score,
            })

        return results