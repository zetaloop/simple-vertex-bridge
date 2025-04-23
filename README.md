# Simple Vertex Bridge

A simple Vertex AI proxy that automatically refresh tokens for you.

[[中文]](README.zh.md)

## Feature
- OpenAI style chat completion API with token attached
- OpenAI style model list API
- Automatically refresh tokens
- Stream output
- Reused h2 connection

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
- Model List: `http://localhost:8086/v1/models`, v1 can be omitted.
- API Endpoint: `http://localhost:8086/v1/chat/completions`, v1 can be omitted.
- API Key: Default is anything (if you specify a key, you must use it), will be replaced with Vertex AI token.

## CLI Arguments
The bridge uses a configuration file `svbridge-config.json` located in the current working directory. It's created automatically on the first run if it doesn't exist.

You can override the configuration using command-line arguments when launching the bridge. These arguments will also update the configuration file.

- `-p [PORT]`, `--port [PORT]`: Port to listen on (default: 8086).
- `-b [BIND]`, `--bind [BIND]`: Host address to bind to (default: localhost).
- `-k [KEY]`, `--key [KEY]`: Specify the API key required for authentication. If not set (default), any key will be accepted.
- `--auto-refresh`/`--no-auto-refresh`: Enable/disable automatic background refresh of the Vertex token (default: enabled).
- `--filter-model-names`/`--no-filter-model-names`: Enable/disable filtering of common model names in the `/models` endpoint (default: enabled).
- `-h`, `--help`: Show help message.

Example:
```bash
# Run publicly on port 8848 and set key 'svb-cRztHvmE50'
python svbridge.py -p 8848 -b 0.0.0.0 -k svb-cRztHvmE50
```

## License

The Unlicense.

TBH I dont care what you do with this code, just dont sue me if it breaks something. uwu
