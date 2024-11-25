"""FastAPI server for the local truck optimization interface."""

import argparse
from dataclasses import asdict
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
import uvicorn

from .model import Scenario, Simulation
from .schemas import ErrorResponse, ScenarioRequest, SimulationResponse

app = FastAPI(title="Truck Optimization MVP API", version="0.1.0")
INDEX = Path(__file__).with_name("static") / "index.html"
# Salabim uses a process-wide default environment. Keep each calculation isolated
# from other requests while FastAPI continues to serve the interface and docs.
simulation_lock = Lock()


@app.middleware("http")
async def response_policy(request: Request, call_next):
    if request.method == "POST" and request.url.path == "/api/simulate":
        if len(await request.body()) > 32768:
            return JSONResponse(status_code=400, content={"error": "Send a small JSON scenario"},
                                headers={"Cache-Control": "no-store"})
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    issue = exc.errors()[0]
    location = ".".join(str(p) for p in issue["loc"] if p != "body")
    message = f"{location}: {issue['msg']}" if location else issue["msg"]
    # Preserve the existing browser API: HTTP 400 and a readable error string.
    return JSONResponse(status_code=400, content={"error": message})


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)},
                        headers=exc.headers)


@app.get("/", response_class=FileResponse, include_in_schema=False)
def index():
    return FileResponse(INDEX, media_type="text/html")


@app.get("/favicon.ico", status_code=204, include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.get("/api/defaults", response_model=ScenarioRequest, summary="Default synthetic scenario")
def defaults():
    return asdict(Scenario())


@app.post("/api/simulate", response_model=SimulationResponse, responses={400: {"model": ErrorResponse}},
          summary="Calculate the truck plan")
def simulate(payload: ScenarioRequest):
    try:
        scenario = payload.to_scenario()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with simulation_lock:
        model = Simulation(scenario)
        result = model.run()
        return {
            "scenario": asdict(scenario),
            "summary": asdict(result),
            "network": model.network.to_dict(),
            "assignments": [asdict(a) for a in model.assignments],
            "events": [asdict(e) for e in model.events],
            "motion": [asdict(m) for m in model.motion],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
