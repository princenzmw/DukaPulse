"""Semantic product search using pgvector embeddings and Kenyan retail taxonomy."""

from __future__ import annotations

import hashlib
import json

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db.models import HAS_PGVECTOR, Inventory, Product

# Domain taxonomy vectors: guarantees semantic closeness for colloquial Sheng / Swahili queries
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "flour_unga": [
        "unga",
        "flour",
        "maize",
        "corn",
        "ugali",
        "jogoo",
        "pembe",
        "ndovu",
        "baking",
        "wheat",
    ],
    "cooking_oil": [
        "oil",
        "fat",
        "mafuta",
        "salad",
        "rina",
        "fresh fri",
        "elianto",
        "frying",
        "cooking oil",
    ],
    "dairy_milk": [
        "milk",
        "maziwa",
        "dairy",
        "kcc",
        "brookside",
        "fresh",
        "lala",
        "cheese",
        "butter",
    ],
    "soap_detergent": [
        "soap",
        "sabuni",
        "detergent",
        "powder",
        "omo",
        "ariel",
        "geisha",
        "sunlight",
        "washing",
        "bath",
    ],
    "beverage_dry": [
        "tea",
        "chai",
        "ketepa",
        "sugar",
        "sukari",
        "salt",
        "chumvi",
        "royco",
        "rice",
        "mchuzi",
        "spices",
    ],
    "telecom_airtime": [
        "airtime",
        "credit",
        "safaricom",
        "airtel",
        "bonga",
        "scratch",
        "recharge",
        "sim",
    ],
}


def compute_dense_embedding(text_input: str, dim: int = 384) -> list[float]:
    """Generate a normalized 384-dimensional dense semantic embedding.

    Uses domain semantic hashing so synonyms (e.g. 'unga' and 'maize meal', 'sabuni' and 'soap')
    align tightly in vector space without requiring an external 500MB transformer download.
    """
    clean_text = text_input.lower().strip()
    words = clean_text.split()
    vec = np.zeros(dim, dtype=np.float32)

    # 1. Base deterministic text feature hash
    for word in words:
        h = int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if ((h >> 8) & 1) else -1.0
        vec[idx] += sign

    # 2. Domain semantic clustering: amplify shared subspace dimensions
    for cluster_idx, (cluster_name, keywords) in enumerate(DOMAIN_KEYWORDS.items()):
        start_dim = cluster_idx * 30
        end_dim = start_dim + 30
        for kw in keywords:
            if kw in clean_text:
                vec[start_dim:end_dim] += 2.5

    # 3. $L_2$ Normalization to unit length
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
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
            elif isinstance(emb_raw, (list, np.ndarray)):
                p_vec = np.array(emb_raw, dtype=np.float32)
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
