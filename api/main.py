import base64
import os
import secrets
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from api.routes import dashboard_api, evaluation, extract, health  # noqa: E402

app = FastAPI(
    title="Invoice Extraction Pipeline",
    description="Extract validated invoice JSON from PDFs and images, evaluate accuracy and cost, "
                "run batches and custom templates, and expose the pipeline as MCP tools.",
    version="1.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,   # "*" origins with credentials is rejected by browsers
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional login for hosted deployments. The sample documents are confidential and every
# extraction spends API quota, so a public URL should set APP_PASSWORD (user: APP_USER, default "admin").
_APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
_APP_USER = os.environ.get("APP_USER", "admin").strip() or "admin"
_OPEN_PATHS = {"/health"}  # platform health checks


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if not _APP_PASSWORD or request.url.path in _OPEN_PATHS:
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            user, _, pwd = base64.b64decode(header[6:]).decode("utf-8").partition(":")
            if secrets.compare_digest(user, _APP_USER) and secrets.compare_digest(pwd, _APP_PASSWORD):
                return await call_next(request)
        except Exception:
            pass
    return Response("Authentication required", status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="Invoice Pipeline"'})


app.include_router(health.router)
app.include_router(extract.router)
app.include_router(evaluation.router)
app.include_router(dashboard_api.router)

static_dir = BASE_DIR / "dashboard" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_dashboard():
        return FileResponse(str(static_dir / "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
