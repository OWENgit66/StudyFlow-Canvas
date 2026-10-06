"""Optional local cross-encoder for bounded candidate experiments only."""
from dataclasses import dataclass
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
from typing import Protocol

from app.core.config import PROJECT_ROOT

RERANK_MODEL = 'cross-encoder/mmarco-mMiniLMv2-L12-H384-v1'
RERANK_FILE = 'onnx/model_quint8_avx2.onnx'
RERANK_CACHE = PROJECT_ROOT/'data/reranker-models'


class RerankerProvider(Protocol):
    def score(self, query: str, documents: list[str]) -> list[float]: ...


class LocalRerankerProvider:
    def __init__(self, *, cache_dir=RERANK_CACHE, allow_download=False):
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        from fastembed.common.model_description import ModelSource
        from tokenizers import Tokenizer
        if RERANK_MODEL not in {m['model'] for m in TextCrossEncoder.list_supported_models()}:
            TextCrossEncoder.add_custom_model(model=RERANK_MODEL,
                sources=ModelSource(hf=RERANK_MODEL), model_file=RERANK_FILE,
                description='Multilingual mMARCO MiniLMv2, official INT8 ONNX',
                license='apache-2.0', size_in_gb=0.119)
        self.encoder = TextCrossEncoder(model_name=RERANK_MODEL, cache_dir=str(cache_dir),
            threads=2, providers=['CPUExecutionProvider'], local_files_only=not allow_download)
        self.model = RERANK_MODEL
        tokenizer = self.encoder.model.tokenizer
        self.max_tokens = tokenizer.truncation['max_length']
        self.counter = Tokenizer.from_str(tokenizer.to_str())
        self.counter.no_truncation()
        self.counter.no_padding()
        root = Path(self.encoder.model._model_dir)
        digest = hashlib.sha256()
        for file in sorted(root.rglob('*')):
            if file.is_file() and file.suffix in {'.onnx', '.json', '.txt'}:
                digest.update(file.relative_to(root).as_posix().encode())
                with file.open('rb') as stream:
                    digest.update(hashlib.file_digest(stream, 'sha256').digest())
        self.model_version = hashlib.sha256(json.dumps({
            'files': digest.hexdigest(), 'fastembed': version('fastembed'),
            'onnxruntime': version('onnxruntime'), 'truncation': tokenizer.truncation,
            'score': 'raw-cross-encoder-logit', 'model_file': RERANK_FILE,
        }, sort_keys=True).encode()).hexdigest()

    def is_truncated(self, query, document):
        return len(self.counter.encode(query, document).ids) > self.max_tokens

    def score(self, query, documents):
        if not query.strip() or len(documents) > 10 or any(not text.strip() for text in documents):
            raise ValueError('Require a query and at most ten nonempty candidate texts.')
        if not documents:
            return []
        return list(self.encoder.rerank(query, documents, batch_size=1))


@dataclass(frozen=True)
class RerankedHit:
    original: object
    rerank_score: float
    original_rank: int

    def __getattr__(self, name):
        return getattr(self.original, name)


def rerank_candidates(query, candidates, provider: RerankerProvider):
    """Only reorder the supplied candidates. Keep cosine scores and provenance."""
    if not query.strip() or len(candidates) > 10:
        raise ValueError('Require a query and at most ten candidates.')
    if not candidates:
        return []
    if len({hit.chunk_id for hit in candidates}) != len(candidates):
        raise ValueError('Duplicate candidate chunk IDs.')
    scores = provider.score(query, [hit.text for hit in candidates])
    if len(scores) != len(candidates) or any(type(s) not in (int, float) or not math.isfinite(s) for s in scores):
        raise ValueError('Invalid reranker scores; no silent retrieval fallback.')
    ranked = [RerankedHit(hit, float(score), rank) for rank, (hit, score) in enumerate(zip(candidates, scores), 1)]
    return sorted(ranked, key=lambda hit: (-hit.rerank_score, hit.original_rank))
