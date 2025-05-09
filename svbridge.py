import os
import argparse
import json
import asyncio
import logging
import logging.config
from datetime import datetime, timedelta, timezone
from threading import RLock
from contextlib import asynccontextmanager

import httpx
import uvicorn
from uvicorn.config import LOGGING_CONFIG
from fastapi import FastAPI, Request, HTTPException, Depends, Header, APIRouter
from fastapi.responses import StreamingResponse
from apscheduler.schedulers.background import BackgroundScheduler

# Configurations
CONFIG_FILE = "svbridge-config.json"
DEFAULT_CONFIG: dict[str, str | bool | int | None] = {
    "port": 8086,
    "bind": "localhost",
    "key": "",
    "access_token": None,
    "token_expiry": None,
    "auto_refresh": True,
    "filter_model_names": True,
}

LOCATION = "us-central1"
PROJECT_ID = None  # to be set on startup
ENDPOINT_ID = "openapi"
PUBLISHERS = (
    "google",
    "anthropic",
    "meta",
)  # No api to list them all, you can manually add them
MODEL_NAMES_FILTER = (
    "google/gemini-",
    "anthropic/claude-",
    "meta/llama",
)  # Usually you wouldnt want to sift through hundreds of irrelevant ones

TOKEN_EXPIRY_BUFFER = timedelta(minutes=10)
BACKGROUND_INTERVAL = 5  # minutes


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event to load config on startup"""
    await startup_event()
    yield
    await shutdown_event()


app = FastAPI(lifespan=lifespan)
router = APIRouter()
token_lock = RLock()
config: dict[str, str | bool | int | None] = {}
logging.config.dictConfig(LOGGING_CONFIG)
logger: logging.Logger = logging.getLogger("uvicorn")
http_client: httpx.AsyncClient | None = None  # Reusable httpx client


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
            logger.warning(f"[Config] No config file found, using defaults")
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
    assert project_id, "Project ID not found, please set up gcloud authentication"
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


async def verify_token(authorization: str | None = Header(None)):
    """Verify the Bearer token if key is set"""
    auth_key = config.get("key")
    if auth_key:  # Only check if key is set
        if not authorization:
            logger.warning("[Auth] Missing Authorization header")
            raise HTTPException(status_code=401, detail="Missing Authorization header")

        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            logger.warning(
                f"[Auth] Invalid Authorization header format: {authorization}"
            )
            raise HTTPException(
                status_code=401, detail="Invalid Authorization header format"
            )

        token = parts[1]
        if token != auth_key:
            logger.warning("[Auth] Invalid token")
            raise HTTPException(status_code=401, detail="Invalid token")
        logger.info("[Auth] Token verified successfully")


@app.get("/")
async def root():
    return "Hello, this is Simple Vertex Bridge! UwU"


@router.api_route(
    "/chat/completions",
    methods=["GET", "POST"],
    dependencies=[Depends(verify_token)],
)
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
        assert http_client
        async with http_client.stream(
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


@router.api_route("/models", methods=["GET"], dependencies=[Depends(verify_token)])
async def models(request: Request):
    """Fetches available models from Vertex and returns them in OpenAI format"""
    assert PROJECT_ID
    logger.info(f"[Models] Received request: {request.url.path}")
    token = get_token()
    if not token:
        logger.error("[Models] No valid token for models request")
        raise HTTPException(status_code=500, detail="Failed to obtain token")

    # Get all publishers asynchronously
    logger.info(f"[Models] Fetching models from {len(PUBLISHERS)} publishers...")

    async def retry_request(session, publisher, url, headers, max_retries=3):
        for attempt in range(max_retries):
            try:
                response = await session.get(url, headers=headers)
                logger.info(f"[Models] {response.status_code} {publisher}")
                return response
            except httpx.RequestError as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f'[Models] Failed to fetch models for publisher "{publisher}", will retry in 200ms: {type(e).__name__}'
                        + (f", {e}" if str(e) else "")
                    )
                    await asyncio.sleep(0.2)
                    continue
                return e

    assert http_client
    tasks = [
        retry_request(
            http_client,
            publisher,
            f"https://{LOCATION}-aiplatform.googleapis.com/v1beta1/publishers/{publisher}/models",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "x-goog-user-project": PROJECT_ID,
            },
        )
        for publisher in PUBLISHERS
    ]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    # Convert to OpenAI format
    all_models = []
    for publisher, resp in zip(PUBLISHERS, responses):
        if isinstance(resp, Exception):
            logger.warning(
                f'[Models] Failed to fetch models for publisher "{publisher}": {type(resp).__name__}'
                + (f", {resp}" if str(resp) else "")
            )
            continue
        assert isinstance(resp, httpx.Response)
        if resp.status_code == 200:
            data = resp.json()
            publisher_models = data.get("publisherModels", [])
            for model in publisher_models:
                name = model.get("name")
                if name:
                    parts = name.split("/")
                    if (
                        len(parts) == 4
                        and parts[0] == "publishers"
                        and parts[2] == "models"
                    ):
                        model_publisher = parts[1]
                        model_name = parts[3]
                        model_id = f"{model_publisher}/{model_name}"
                        all_models.append(
                            {
                                "id": model_id,
                                "object": "model",
                                "owned_by": model_publisher,
                            }
                        )
        else:
            logger.warning(
                f'[Models] Failed to fetch models for publisher "{publisher}": {resp.status_code} {resp.text}.'
            )

    # Prefix filter
    if config.get("filter_model_names", True):
        all_models_count = len(all_models)
        all_models = [
            model
            for model in all_models
            if any(model["id"].startswith(prefix) for prefix in MODEL_NAMES_FILTER)
        ]
        logger.info(f"[Models] Fetched {len(all_models)}/{all_models_count} models")
    else:
        logger.info(f"[Models] Fetched {len(all_models)} models")

    return {"object": "list", "data": all_models}


app.include_router(router)
app.include_router(router, prefix="/v1")


async def startup_event():
    """Startup event"""
    global http_client
    logger.info("[HTTPClient] Creating reusable client...")
    http_client = httpx.AsyncClient(http2=True, timeout=None)
    logger.info("[HTTPClient] Created reusable client")

    global PROJECT_ID
    logger.info("[Google] Getting default project ID...")
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


async def shutdown_event():
    """Shutdown event"""
    global http_client
    if http_client:
        await http_client.aclose()
        logger.info("[HTTPClient] Closed reusable client")
        http_client = None


def main():
    """Entry point"""
    parser = argparse.ArgumentParser(description="Simple Vertex Bridge /UwU")
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        nargs="?",
        const=8086,
        help="Port to listen on (default: 8086)",
    )
    parser.add_argument(
        "-b",
        "--bind",
        type=str,
        nargs="?",
        const="localhost",
        help="Host to bind to (default: localhost)",
    )
    parser.add_argument(
        "-k",
        "--key",
        type=str,
        nargs="?",
        const="",
        help="Specify the API key, if not set (as default), accept any key",
    )

    # Boolean flags for auto-refresh
    refresh_group = parser.add_mutually_exclusive_group()
    refresh_group.add_argument(
        "--auto-refresh",
        action=argparse.BooleanOptionalAction,
        dest="auto_refresh",
        help="Background token refresh check every 5 minutes (default: on)",
    )

    # Boolean flags for model filtering
    filter_group = parser.add_mutually_exclusive_group()
    filter_group.add_argument(
        "--filter-model-names",
        action=argparse.BooleanOptionalAction,
        dest="filter_model_names",
        help="Filtering common model names (default: on)",
    )

    args = parser.parse_args()

    load_config()
    config_updated = False
    for key, value in vars(args).items():
        if value is not None:  # Check if the argument was actually passed
            if config.get(key) != value:
                config[key] = value
                config_updated = True
    if config_updated:
        save_config()

    bind = config.get("bind")
    port = config.get("port")
    key = config.get("key")
    assert isinstance(bind, str)
    assert isinstance(port, int)
    assert isinstance(key, str)

    logger.info(f"--------")
    logger.info(f"Server: http://{bind}:{port}")
    if bind not in ("localhost", "127.0.0.1", "::1") and not key:
        logger.warning(f"[Auth] Server is exposed to the internet, PLEASE SET A KEY!")
    elif key:
        logger.info(f'API key: "{key}"')
    logger.info(f"--------")
    uvicorn.run("svbridge:app", host=bind, port=port)


if __name__ == "__main__":
    main()
