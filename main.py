"""
ChaosLab - FastAPI sunucusu
Çalıştırma:  uvicorn main:app --reload   (veya)   python main.py
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from chaos_engine import (
    PRESETS, ChaosError, basin_analysis, bifurcation_analysis, compare_systems, full_analysis,
    poincare_analysis,
)
from map_engine import MAP_PRESETS, map_basin, map_bifurcation, map_compare, map_full_analysis

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="ChaosLab – Kaotik Sistem Analiz Laboratuvarı",
    version="1.0.0",
    description="N boyutlu (1–10) sürekli ve ayrık zamanlı doğrusal olmayan sistemlerin sembolik ve sayısal analizi.",
)
app.add_middleware(GZipMiddleware, minimum_size=2048)


class AnalyzeRequest(BaseModel):
    equations: list[str] = Field(..., min_length=1, max_length=10)
    params: str = ""
    initial: list[float] = Field(..., min_length=1, max_length=10)
    t_max: float = Field(100.0, gt=0, le=100_000)
    dt: float = Field(0.01, gt=0, le=10)
    delta0: float = Field(1e-5, gt=0, le=1)
    lyap_t: float = Field(300.0, gt=0, le=100_000)
    lyap_dt: float = Field(0.01, gt=0, le=10)
    lyap_transient: float = Field(20.0, ge=0, le=100_000)
    compute_lyapunov: bool = True
    method: Literal["DOP853", "RK45", "LSODA", "Radau"] = "DOP853"


class BifurcationRequest(BaseModel):
    equations: list[str] = Field(..., min_length=1, max_length=10)
    params: str = ""
    initial: list[float] = Field(..., min_length=1, max_length=10)
    param: str
    p_min: float
    p_max: float
    steps: int = Field(200, ge=2, le=2000)
    var: str = "x"
    t_transient: float = Field(50.0, ge=0)
    t_total: float = Field(150.0, gt=0)
    dt: float = Field(0.01, gt=0, le=10)


@app.get("/api/presets")
def get_presets() -> dict:
    return PRESETS


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    t0 = time.perf_counter()
    try:
        result = full_analysis(
            equations=req.equations,
            params=req.params,
            initial=req.initial,
            t_max=req.t_max,
            dt=req.dt,
            delta0=req.delta0,
            lyap_t=req.lyap_t,
            lyap_dt=req.lyap_dt,
            lyap_transient=req.lyap_transient,
            compute_lyapunov=req.compute_lyapunov,
            method=req.method,
        )
    except ChaosError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Beklenmeyen hata: {type(exc).__name__}: {exc}") from exc
    result["elapsed"] = round(time.perf_counter() - t0, 3)
    return result


@app.post("/api/bifurcation")
def bifurcation(req: BifurcationRequest) -> dict:
    t0 = time.perf_counter()
    try:
        result = bifurcation_analysis(
            equations=req.equations,
            params=req.params,
            initial=req.initial,
            param=req.param,
            p_min=req.p_min,
            p_max=req.p_max,
            steps=req.steps,
            var=req.var,
            t_transient=req.t_transient,
            t_total=req.t_total,
            dt=req.dt,
        )
    except ChaosError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Beklenmeyen hata: {type(exc).__name__}: {exc}") from exc
    result["elapsed"] = round(time.perf_counter() - t0, 3)
    return result


class PoincareRequest(BaseModel):
    equations: list[str] = Field(..., min_length=1, max_length=10)
    params: str = ""
    initial: list[float] = Field(..., min_length=1, max_length=10)
    plane_var: str = "z"
    plane_value: float = 0.0
    direction: int = Field(1, ge=-1, le=1)
    t_transient: float = Field(50.0, ge=0)
    t_max: float = Field(1000.0, gt=0)


class BasinRequest(BaseModel):
    equations: list[str] = Field(..., min_length=1, max_length=10)
    params: str = ""
    initial: list[float] = Field(..., min_length=1, max_length=10)
    var_a: str = "x"
    var_b: str = "y"
    a_min: float
    a_max: float
    b_min: float = 0.0
    b_max: float = 1.0
    res: int = Field(80, ge=10, le=600)
    t_total: float = Field(30.0, gt=0)
    dt: float = Field(0.01, gt=0, le=10)
    n_iter: int = Field(300, ge=10, le=100_000)
    override: str = ""


class CompareRequest(BaseModel):
    keys: list[str] = Field(..., min_length=1, max_length=16)


class MapAnalyzeRequest(BaseModel):
    equations: list[str] = Field(..., min_length=1, max_length=10)
    params: str = ""
    initial: list[float] = Field(..., min_length=1, max_length=10)
    n_iter: int = Field(5000, ge=20, le=500_000)
    transient: int = Field(200, ge=0, le=400_000)
    delta0: float = Field(1e-8, gt=0, le=1)
    lyap_n: int = Field(20000, ge=10, le=500_000)
    compute_lyapunov: bool = True


class MapBifurcationRequest(BaseModel):
    equations: list[str] = Field(..., min_length=1, max_length=10)
    params: str = ""
    initial: list[float] = Field(..., min_length=1, max_length=10)
    param: str
    p_min: float
    p_max: float
    steps: int = Field(800, ge=2, le=3000)
    var: str = "x"
    transient: int = Field(500, ge=0, le=100_000)
    keep: int = Field(200, ge=1, le=2000)


def _run(fn, *args, **kwargs) -> dict:
    t0 = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
    except ChaosError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Beklenmeyen hata: {type(exc).__name__}: {exc}") from exc
    result["elapsed"] = round(time.perf_counter() - t0, 3)
    return result


@app.post("/api/poincare")
def poincare(req: PoincareRequest) -> dict:
    return _run(poincare_analysis, req.equations, req.params, req.initial, req.plane_var,
                req.plane_value, req.direction, req.t_transient, req.t_max)


@app.post("/api/basin")
def basin(req: BasinRequest) -> dict:
    if req.res > 400:
        raise HTTPException(status_code=400, detail="Sürekli sistemlerde çözünürlük ≤ 400 olmalı.")
    return _run(basin_analysis, req.equations, req.params, req.initial, req.var_a, req.var_b,
                req.a_min, req.a_max, req.b_min, req.b_max, req.res, req.t_total, req.dt, req.override)


@app.post("/api/compare")
def compare(req: CompareRequest) -> dict:
    return _run(compare_systems, req.keys)


@app.get("/api/map/presets")
def get_map_presets() -> dict:
    return MAP_PRESETS


@app.post("/api/map/analyze")
def map_analyze(req: MapAnalyzeRequest) -> dict:
    return _run(map_full_analysis, req.equations, req.params, req.initial, req.n_iter,
                req.transient, req.delta0, req.lyap_n, req.compute_lyapunov)


@app.post("/api/map/bifurcation")
def map_bif(req: MapBifurcationRequest) -> dict:
    return _run(map_bifurcation, req.equations, req.params, req.initial, req.param, req.p_min,
                req.p_max, req.steps, req.var, req.transient, req.keep)


@app.post("/api/map/basin")
def map_basin_ep(req: BasinRequest) -> dict:
    return _run(map_basin, req.equations, req.params, req.initial, req.var_a, req.var_b,
                req.a_min, req.a_max, req.b_min, req.b_max, req.res, req.n_iter, req.override)


@app.post("/api/map/compare")
def map_compare_ep(req: CompareRequest) -> dict:
    return _run(map_compare, req.keys)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    import os

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
