"""Local embedding only. No generation providers, credentials or remote inference."""
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
from typing import Protocol

from app.core.config import PROJECT_ROOT

DEFAULT_MODEL = 'BAAI/bge-small-en-v1.5'
DEFAULT_CACHE = PROJECT_ROOT / 'data' / 'embedding-models'


class EmbeddingProvider(Protocol):
    model: str
    model_version: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def unit_vector(values, dimensions=None):
    vector = list(values)
    if (not vector or (dimensions is not None and len(vector) != dimensions)
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector)):
        raise ValueError('Invalid embedding values or dimensions.')
    scale = max(abs(x) for x in vector)
    if not scale:
        raise ValueError('Zero embedding vector.')
    scaled = [x / scale for x in vector]
    norm = math.sqrt(sum(x*x for x in scaled))
    return [x / norm for x in scaled]


class LocalEmbeddingProvider:
    """FastEmbed CPU. Model download must be explicitly enabled; then offline.

    Long existing chunks are pooled over token windows to avoid silent model
    truncation. Windows are temporary model input, never new DocumentChunks.
    """
    def __init__(self, *, model=DEFAULT_MODEL, cache_dir=DEFAULT_CACHE, allow_download=False):
        from fastembed import TextEmbedding
        from tokenizers import Tokenizer

        self.model = model
        self.encoder = TextEmbedding(model_name=model, cache_dir=str(cache_dir),
            threads=2, providers=['CPUExecutionProvider'], local_files_only=not allow_download)
        self.dimensions = self.encoder.embedding_size
        # The optional dependency is pinned; isolate its tokenizer/layout access here.
        self.tokenizer = Tokenizer.from_str(self.encoder.model.tokenizer.to_str())
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.window_tokens = min(480, self.encoder.model.tokenizer.truncation['max_length'] - 32)
        root = Path(self.encoder.model._model_dir)
        digest = hashlib.sha256()
        for file in sorted(root.rglob('*')):
            if file.is_file() and file.suffix in {'.onnx', '.json', '.txt'}:
                digest.update(file.relative_to(root).as_posix().encode())
                with file.open('rb') as stream:
                    digest.update(hashlib.file_digest(stream, 'sha256').digest())
        profile = {'weights': digest.hexdigest(), 'fastembed': version('fastembed'),
                   'onnxruntime': version('onnxruntime'), 'window_tokens': self.window_tokens,
                   'pooling': 'token-weighted-normalized-windows-v1'}
        self.model_version = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()

    def _windows(self, text):
        if not text.strip():
            raise ValueError('Embedding text must not be empty.')
        tokens = self.tokenizer.encode(text, add_special_tokens=False)
        for start in range(0, len(tokens.offsets), self.window_tokens):
            offsets = tokens.offsets[start:start+self.window_tokens]
            yield text[offsets[0][0]:offsets[-1][1]], len(offsets)

    def embed(self, texts):
        windows, owners, weights = [], [], []
        for index, text in enumerate(texts):
            for window, weight in self._windows(text):
                windows.append(window)
                owners.append(index)
                weights.append(weight)
        totals = [[0.0] * self.dimensions for _ in texts]
        for owner, weight, encoded in zip(owners, weights,
                self.encoder.passage_embed(windows, batch_size=16), strict=True):
            vector = unit_vector(encoded.tolist(), self.dimensions)
            for i, value in enumerate(vector):
                totals[owner][i] += weight * value
        return [unit_vector(vector, self.dimensions) for vector in totals]

    def embed_query(self, text):
        if not text.strip() or len(self.tokenizer.encode(text).ids) > self.window_tokens:
            raise ValueError('Query is empty or exceeds the local model token budget.')
        return unit_vector(next(self.encoder.query_embed(text)).tolist(), self.dimensions)
