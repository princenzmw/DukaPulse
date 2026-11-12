"""pgvector semantic catalog search tests with real all-MiniLM-L6-v2 embeddings."""

from __future__ import annotations

import numpy as np

from dukapulse.services.semantic_search import SemanticSearchService, compute_dense_embedding


def test_embedding_dimension_and_norm():
    """Verify vectors are 384 dimensions and normalized to unit length."""
    vec = compute_dense_embedding("unga ya ugali")
    assert len(vec) == 384
    norm = np.linalg.norm(vec)
    assert abs(norm - 1.0) < 1e-4


def test_semantic_synonym_retrieval(db_session):
    """Verify colloquial Swahili / Sheng queries correctly rank related items at the top

    with measured cosine similarities.
    """
    service = SemanticSearchService(db_session)
    shop_id = "shop_kibera_01"

    # 1. Search 'unga ya ugali' -> Matches Pembe & Jogoo Maize Meal
    results_unga = service.search_products(shop_id, query="unga ya ugali", top_k=3)
    names_unga = [r["name"] for r in results_unga]
    sims_unga = [r["similarity"] for r in results_unga]
    assert any("Jogoo" in n for n in names_unga)
    assert any("Pembe" in n for n in names_unga)
    assert sims_unga[0] > 0.70

    # 2. Search 'sabuni ya kuoga' -> Matches Geisha Bath Soap top
    results_soap = service.search_products(shop_id, query="sabuni ya kuoga", top_k=3)
    assert "Geisha" in results_soap[0]["name"]
    assert results_soap[0]["similarity"] > 0.55

    # 3. Search 'mafuta ya kupika' -> Matches Fresh Fri & Rina Cooking Oil
    results_oil = service.search_products(shop_id, query="mafuta ya kupika", top_k=3)
    names_oil = [r["name"] for r in results_oil]
    assert any("Rina" in n or "Fresh Fri" in n for n in names_oil)
    assert results_oil[0]["similarity"] > 0.60
