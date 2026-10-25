"""Mesh API embeddings via its OpenAI-compatible embeddings endpoint."""


class Embedder:
    def __init__(
        self, api_key: str, base_url: str, model_name: str = "text-embedding-3-small", dimensions: int = 1536
    ):
        if not api_key:
            raise ValueError("MESH_API_KEY is required for embeddings")
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model_name = model_name
        self._dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str], max_workers: int = 1) -> list[list[float]]:
        del max_workers
        if not texts:
            return []
        result: list[list[float]] = []
        # Small batches keep request payloads bounded and make failures easier to retry.
        for start in range(0, len(texts), 64):
            batch = texts[start : start + 64]
            response = self._client.embeddings.create(
                model=self._model_name,
                input=[text[:30000] for text in batch],
                dimensions=self._dimensions,
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            result.extend([[float(value) for value in item.embedding] for item in ordered])
        if len(result) != len(texts):
            raise RuntimeError("Embedding API returned a different number of vectors than inputs")
        wrong = [i for i, vector in enumerate(result) if len(vector) != self._dimensions]
        if wrong:
            raise RuntimeError(
                f"Embedding model returned an unexpected dimension; expected {self._dimensions}, "
                f"wrong vector indexes: {wrong[:5]}"
            )
        return result
