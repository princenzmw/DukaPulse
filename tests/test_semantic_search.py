"""pgvector semantic catalog search tests."""

from __future__ import annotations

from dukapulse.services.semantic_search import SemanticSearchService, compute_dense_embedding


def test_embedding_dimension_and_norm():
    """Verify vectors are 384 dimensions and normalized to unit length."""
    import numpy as np

    vec = compute_dense_embedding("unga ya ugali")
    assert len(vec) == 384
    norm = np.linalg.norm(vec)
    assert abs(norm - 1.0) < 1e-4


def test_semantic_synonym_retrieval(db_session):
    """Verify colloquial Swahili / Sheng queries correctly rank related items at the top."""
    service = SemanticSearchService(db_session)
    shop_id = "shop_kibera_01"

    # 1. Search 'unga' -> Should match Jogoo or Pembe Maize Meal
    results_unga = service.search_products(shop_id, query="unga wa ugali", top_k=3)
    top_name = results_unga[0]["name"].lower()
    assert "maize" in top_name or "unga" in top_name or "flour" in top_name

    # 2. Search 'sabuni ya kuoga' -> Should match Geisha Soap
    results_soap = service.search_products(shop_id, query="sabuni ya kuoga", top_k=3)
    top_soap = results_soap[0]["name"].lower()
    assert "soap" in top_soap or "geisha" in top_soap or "omo" in top_soap

    # 3. Search 'mafuta ya kupikia' -> Should match Rina or Fresh Fri
    results_oil = service.search_products(shop_id, query="mafuta ya kupikia", top_k=3)
    top_oil = results_oil[0]["name"].lower()
    assert "oil" in top_oil or "rina" in top_oil or "fri" in top_oil
