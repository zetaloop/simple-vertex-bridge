import os
import json
import logging
from datetime import datetime, timedelta, timezone
from threading import RLock
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from apscheduler.schedulers.background import BackgroundScheduler

# Configurations
CONFIG_FILE = "svbridge-config.json"
DEFAULT_CONFIG: dict[str, str | bool | None] = {
    "access_token": None,
    "token_expiry": None,
    "auto_refresh": True,
}

LOCATION = "us-central1"
PROJECT_ID = None  # to be set on startup
ENDPOINT_ID = "openapi"

TOKEN_EXPIRY_BUFFER = timedelta(minutes=10)
BACKGROUND_INTERVAL = 5  # minutes


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event to load config on startup"""
    startup_event()
    yield
    shutdown_event()


app = FastAPI(lifespan=lifespan)
token_lock = RLock()
config: dict[str, str | bool | None] = {}
logger = logging.getLogger("uvicorn")


def load_config():
    """Load or initialize the config file"""
    global config
    with token_lock:
        is_changed = True
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    json_data = json.load(f)
                    config.update(json_data)
                    if config == json_data:
                        is_changed = False
                logger.info(f'[Config] Loaded <== "{CONFIG_FILE}"')
            except json.JSONDecodeError as e:
                logger.error(f"[Config] Failed to load config and using defaults: {e}")
                config = DEFAULT_CONFIG.copy()
        else:
            logger.info(f"[Config] No config file found, using defaults")
            config = DEFAULT_CONFIG.copy()
        for k, v in DEFAULT_CONFIG.items():
            config.setdefault(k, v)

        if is_changed:
            save_config()


def save_config():
    """Save config file"""
    with token_lock:
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=4)
            logger.info(f'[Config] Saved ==> "{CONFIG_FILE}"')
        except Exception as e:
            logger.error(f"[Config] Failed to save config: {e}")


def get_gcloud_project_id() -> str:
    """Get the gcloud project ID"""
    from google.auth import default

    # If this fails, you need to set up gcloud authentication
    _, project_id = default()
    assert project_id, "Project ID not found"
    return project_id


def generate_gcloud_token() -> tuple[str, datetime] | tuple[None, None]:
    """Get a new token using gcloud sdk"""
    from google.auth import default
    from google.auth.transport.requests import Request

    try:
        credentials, _ = default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(Request())
        token = credentials.token
        expiry = credentials.expiry.replace(tzinfo=timezone.utc)
        return token, expiry
    except Exception as e:
        logger.error(f"[Token] Failed to fetch token: {e}")
        return None, None


def is_valid() -> bool:
    """Check whether the local token exists and is not expired (with buffer)"""
    with token_lock:
        token = config.get("access_token")
        exp = config.get("token_expiry")
    if not token or not exp:
        logger.info("[Token] Token invalid: missing token or expiry")
        return False
    try:
        assert isinstance(token, str)
        assert isinstance(exp, str)
        expiry = datetime.fromisoformat(exp)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now < (expiry - TOKEN_EXPIRY_BUFFER):
            logger.info(f"[Token] Token valid until {expiry}")
            return True
        logger.info(f"[Token] Token expired at {expiry}")
        return False
    except ValueError as e:
        logger.error(f"[Token] Invalid expiry format: {e}")
        return False


def refresh_token(force=False):
    """Refresh token"""
    with token_lock:
        if force or not is_valid():
            new_token, new_exp = generate_gcloud_token()
            if new_token and new_exp:
                config["access_token"] = new_token
                config["token_expiry"] = new_exp.isoformat()
                save_config()
                logger.info("[Token] Token refreshed")
                return True
            logger.error("[Token] Token refresh failed")
            return False
        logger.info("[Token] No refresh needed")
        return True


def get_token():
    """Get current token, refresh when expired"""
    with token_lock:
        if not is_valid():
            logger.warning("[Token] Token expired, forcing refresh")
            if not refresh_token(force=True):
                logger.error("[Token] Failed to get token")
                return None
        logger.info("[Token] Token retrieved successfully")
        return config.get("access_token")


@app.get("/")
async def root():
    return "Hello, this is Simple Vertex Bridge! UwU"


@app.api_route("/v1/chat/completions", methods=["GET", "POST"])
@app.api_route("/chat/completions", methods=["GET", "POST"])
async def chat_completions(request: Request):
    """Proxy to Vertex AI with Bearer token"""
    logger.info(f"[Proxy] Received request: {request.url.path}")
    token = get_token()
    if not token:
        logger.error("[Proxy] No valid token for proxy request")
        raise HTTPException(status_code=500, detail="Failed to obtain token")

    target = (
        f"https://{LOCATION}-aiplatform.googleapis.com/v1"
        f"/projects/{PROJECT_ID}"
        f"/locations/{LOCATION}"
        f"/endpoints/{ENDPOINT_ID}"
        f"/chat/completions"
    )
    if request.url.query:
        target += f"?{request.url.query}"
    logger.info(f"[Proxy] {request.method} {target}")

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in ("host", "authorization", "content-length")
    }
    headers["Authorization"] = f"Bearer {token}"

    body = await request.body()

    async def stream_with_header():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                request.method,
                target,
                headers=headers,
                content=body,
            ) as resp:
                yield resp.status_code, resp.headers.get("content-type")

                async for chunk in resp.aiter_bytes():
                    yield chunk

    ait = stream_with_header()
    status_code, media_type = await ait.__anext__()
    assert isinstance(status_code, int)
    assert isinstance(media_type, str)

    async def stream_wrapper():
        async for chunk in ait:
            assert isinstance(chunk, bytes)
            yield chunk

    return StreamingResponse(
        stream_wrapper(),
        status_code=status_code,
        media_type=media_type,
    )


def startup_event():
    """Startup event"""
    global PROJECT_ID
    PROJECT_ID = get_gcloud_project_id()
    logger.info(f"[Google] Project ID: {PROJECT_ID}")

    load_config()
    if config.get("auto_refresh"):
        logger.info(
            f"[Background] Started checking token every {BACKGROUND_INTERVAL} minutes"
        )
        scheduler = BackgroundScheduler()
        scheduler.add_job(refresh_token, "interval", minutes=BACKGROUND_INTERVAL)
        scheduler.start()
        refresh_token()  # Run once immediately


def shutdown_event():
    pass


def main():
    """Entry point"""
    uvicorn.run("svbridge:app", host="localhost", port=8086)


if __name__ == "__main__":
    main()
