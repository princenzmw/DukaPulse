"""Semantic product search using sentence-transformers and pgvector embeddings."""

from __future__ import annotations

import functools
import json
import os

import numpy as np
from sentence_transformers import SentenceTransformer
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db.models import HAS_PGVECTOR, Inventory, Product

# Pinned model and revision for deterministic, reproducible embeddings
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"

# Domain synonym dictionary: maps colloquial Kenyan retail terms (Swahili / Sheng)
# into English conceptual tokens so all-MiniLM-L6-v2 accurately bridges vernacular
# consumer searches to formal product catalog entries.
KENYAN_RETAIL_SYNONYMS: dict[str, str] = {
    "unga": "maize flour meal ugali",
    "ugali": "maize meal ugali staple",
    "sabuni": "soap",
    "kuoga": "bathing bath soap body wash bar",
    "kuosha": "laundry washing powder clothes detergent fabric",
    "mafuta": "cooking oil frying fat vegetable",
    "kupika": "cooking oil frying culinary kitchen",
    "maziwa": "fresh dairy cow milk",
    "sukari": "sugar sweetener",
    "chumvi": "salt seasoning",
    "chai": "black tea leaves",
}


@functools.lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    """Singleton cached loader for the pinned sentence-transformers model.

    Reuses the in-memory neural weights across API queries and DB seed runs,
    preventing repeated disk I/O and transformer re-initialization.
    """
    # Prevent warning telemetry during model loading
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    return SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION)


def enrich_kenyan_retail_text(text_input: str) -> str:
    """Enrich colloquial Swahili or Sheng retail phrases with conceptual synonyms.

    Ensures cross-lingual queries align tightly with English catalog descriptions.
    """
    clean_words = text_input.lower().split()
    expansions: list[str] = []
    for word in clean_words:
        if word in KENYAN_RETAIL_SYNONYMS:
            expansions.append(KENYAN_RETAIL_SYNONYMS[word])
    if expansions:
        return f"{text_input} ({' '.join(expansions)})"
    return text_input


def compute_dense_embedding(text_input: str, dim: int = 384) -> list[float]:
    """Generate a normalized 384-dimensional dense semantic embedding.

    Uses sentence-transformers all-MiniLM-L6-v2 with domain synonym enrichment
    and L2 unit normalization.
    """
    clean_text = text_input.strip()
    if not clean_text:
        return [0.0] * dim

    enriched = enrich_kenyan_retail_text(clean_text)
    model = get_embedding_model()
    vec = model.encode(enriched, normalize_embeddings=True)
    return vec.tolist()


class SemanticSearchService:
    """pgvector semantic catalog search with cosine similarity."""

    def __init__(self, db: Session):
        self.db = db

    def search_products(
        self,
        shop_id: str,
        query: str,
        top_k: int = 5,
        category: str | None = None,
    ) -> list[dict]:
        """Search products semantically using pgvector cosine distance (<=>)."""
        query_vec = compute_dense_embedding(query)

        # 1. Native PostgreSQL + pgvector execution path
        if HAS_PGVECTOR and not self.db.bind.dialect.name == "sqlite":
            try:
                cat_filter = "AND p.category = :category" if category else ""
                sql = text(f"""
                    SELECT 
                        p.id, p.name, p.category, p.unit_cost, p.unit_price, p.barcode,
                        i.current_stock, i.reorder_point,
                        (1 - (p.embedding <=> :query_vec::vector)) AS similarity
                    FROM products p
                    JOIN inventory i ON p.id = i.product_id
                    WHERE p.shop_id = :shop_id {cat_filter}
                    ORDER BY p.embedding <=> :query_vec::vector ASC
                    LIMIT :limit;
                """)
                params = {
                    "shop_id": shop_id,
                    "query_vec": str(query_vec),
                    "limit": top_k,
                }
                if category:
                    params["category"] = category
                rows = self.db.execute(sql, params).mappings().all()
                return [dict(r) for r in rows]
            except Exception:
                pass  # Fall through to in-memory cosine fallback

        # 2. In-memory cosine fallback for SQLite / test environments
        products = (
            self.db.query(Product, Inventory)
            .join(Inventory, Product.id == Inventory.product_id)
            .filter(Product.shop_id == shop_id)
            .all()
        )

        results = []
        q_arr = np.array(query_vec, dtype=np.float32)
        q_norm = np.linalg.norm(q_arr)

        for prod, inv in products:
            if category and prod.category != category:
                continue

            emb_raw = prod.embedding
            if isinstance(emb_raw, str):
                try:
                    p_vec = np.array(json.loads(emb_raw), dtype=np.float32)
                except Exception:
                    p_vec = np.array(
                        compute_dense_embedding(prod.name + " " + (prod.description or "")),
                        dtype=np.float32,
                    )
            elif emb_raw is not None and hasattr(emb_raw, "__iter__"):
                p_vec = np.array(list(emb_raw), dtype=np.float32)
            else:
                p_vec = np.array(
                    compute_dense_embedding(prod.name + " " + (prod.description or "")),
                    dtype=np.float32,
                )

            p_norm = np.linalg.norm(p_vec)
            sim = (
                float(np.dot(q_arr, p_vec) / (q_norm * p_norm))
                if (q_norm > 0 and p_norm > 0)
                else 0.0
            )

            results.append(
                {
                    "id": prod.id,
                    "name": prod.name,
                    "category": prod.category,
                    "unit_cost": prod.unit_cost,
                    "unit_price": prod.unit_price,
                    "barcode": prod.barcode,
                    "current_stock": inv.current_stock,
                    "reorder_point": inv.reorder_point,
                    "similarity": round(sim, 4),
                }
            )

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]
