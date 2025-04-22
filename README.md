# Simple Vertex Bridge

A simple Vertex AI proxy that automatically refresh tokens for you.

[[中文]](README.zh.md)

## Usage
### Prerequisites
- Install [uv](https://docs.astral.sh/uv/getting-started/installation).

### Authentication
There are two ways to authenticate:
1. **By gcloud CLI**
   - Install [gcloud CLI](https://cloud.google.com/sdk/docs/install).
   - Run `gcloud auth application-default login` to authenticate.
2. **By service account key**
   - Create a service account key in the Google Cloud Console, according to [this documentation](https://cloud.google.com/iam/docs/keys-create-delete#creating).
   - Download the json key file.
   - Set the `GOOGLE_APPLICATION_CREDENTIALS` environment variable to the path of the key file.

### Launch
- **Note:** `svbridge-config.json` will be created in **the current directory**.
1. You can run `uvx simple-vertex-bridge` to launch the bridge directly from pypi.
2. Or clone this repo and enter and run `uv sync`, then activate venv and run `python svbridge.py`.

### Now your API is ready
- API Endpoint: `http://localhost:8086/v1/chat/completions`, v1 can be omitted.
- API Key: `anything`, the bridge will replace it with the Vertex AI token.

## License

The Unlicense.

TBH I dont care what you do with this code, just dont sue me if it breaks something. uwu
