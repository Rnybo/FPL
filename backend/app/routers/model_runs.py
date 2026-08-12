"""GET /api/model-runs -- transparency: every model fit/backtest we've run,
with its accuracy notes. This is the "never a black box" page's data source --
lets us show, in the UI, exactly what beats naive/FPL's own predictor and
what doesn't (see README.md's "Honest results, not spun" section for the
narrative version of this same data).
"""
from fastapi import APIRouter
from app.services.db import query_df

router = APIRouter(prefix="/api/model-runs", tags=["model-runs"])


@router.get("")
def list_model_runs(model_type: str | None = None, limit: int = 50):
    sql = "SELECT run_id, trained_at, season_range, position_group, model_type, notes FROM model_runs"
    params: tuple = ()
    if model_type:
        sql += " WHERE model_type = ?"
        params = (model_type,)
    sql += " ORDER BY run_id DESC LIMIT ?"
    params = params + (limit,)
    df = query_df(sql, params)
    return {"runs": df.to_dict(orient="records")}


@router.get("/{run_id}/weights")
def get_run_weights(run_id: int):
    df = query_df(
        "SELECT feature_name, weight, position_group FROM model_weights WHERE run_id = ?",
        (run_id,),
    )
    return {"run_id": run_id, "weights": df.to_dict(orient="records")}
