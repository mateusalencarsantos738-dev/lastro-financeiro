from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.app.api import router
from backend.app.settings import settings

app = FastAPI(title="Meu Financeiro", version="0.1.0", docs_url="/api/docs")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
app.include_router(router)

@app.middleware("http")
async def local_origin_guard(request: Request, call_next):
    origin = request.headers.get("origin")
    allowed = {f"http://127.0.0.1:{settings.app_port}", f"http://localhost:{settings.app_port}"}
    if origin and origin not in allowed:
        return JSONResponse({"detail": "Origem não permitida"}, status_code=403)
    return await call_next(request)

dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def frontend(path: str):
        target = (dist / path).resolve()
        if target.is_relative_to(dist.resolve()) and target.is_file():
            return FileResponse(target)
        return FileResponse(dist / "index.html")
