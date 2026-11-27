from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="python-service")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app
