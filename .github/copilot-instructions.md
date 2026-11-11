# GitHub Copilot Instructions for DukaPulse

This codebase is a production micro-retail inventory platform built for African neighborhood kiosks (dukas).

### Key Modules:
- `dukapulse/db/models.py`: Declarative SQLAlchemy models including Shop, Product, Inventory, and SalesEvent (Hypertable).
- `dukapulse/services/inventory.py`: Concurrency-safe inventory processing with pessimistic locks (`with_for_update()`).
- `dukapulse/services/semantic_search.py`: `pgvector` dense vector search with colloquial Kenyan semantic clustering.
- `dukapulse/services/timeseries.py`: Tiger Data Timescale hypertable telemetry and time_bucket continuous rollups.
- `dukapulse/services/forecasting.py`: Backtested demand forecasting benchmarked against seasonal-naive moving baselines.
- `dukapulse/auth/jwt.py`: Auth0 RS256 JWKS token validation with mock HS256 offline development mode.

### Guidelines:
- When modifying inventory operations, never remove `with_for_update()` or omit transaction commits.
- Ensure all API endpoints in `dukapulse/api/routes.py` use appropriate RBAC dependencies (`RequireOwner` vs `RequireStaff`).
- Maintain test coverage across `tests/` with pytest.
