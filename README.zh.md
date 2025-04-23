# Simple Vertex Bridge

一个帮你自动刷新访问令牌的简单 Vertex AI 代理。

[[English]](README.md)

## 功能
- OpenAI 格式的聊天补全 API，自带访问令牌
- OpenAI 格式的模型列表 API
- 自动刷新访问令牌
- 流式输出
- 复用 h2 连接

## 使用指南
### 准备
- 安装 [uv](https://docs.astral.sh/uv/getting-started/installation)。

### 认证
有两种认证方法：
1. **gcloud CLI**
   - 安装 [gcloud CLI](https://cloud.google.com/sdk/docs/install)。
   - 运行 `gcloud auth application-default login` 来进行认证。
2. **服务账号密钥文件**
   - 在谷歌云控制台里创建服务账号密钥，[参考这个教程](https://cloud.google.com/iam/docs/keys-create-delete?hl=zh-cn#creating)。
   - 下载 json 密钥文件。
   - 将环境变量 `GOOGLE_APPLICATION_CREDENTIALS` 设为密钥文件路径。

### 启动
- **注意**：配置文件 `svbridge-config.json` 将会保存到**当前目录**。
1. 可以直接运行 `uvx simple-vertex-bridge` 来启动服务。
2. 也可以克隆仓库后在里边运行 `uv sync`，激活虚拟环境，然后运行 `python svbridge.py`。

### 好了
- 模型列表: `http://localhost:8086/v1/models`，v1 可以省略。
- API 地址: `http://localhost:8086/v1/chat/completions`，v1 可以省略。
- API 密钥: 默认填什么都行，如果指定了一个密钥则必须填密钥，会被替换成 Vertex AI 令牌。

## 命令行参数
服务使用位于当前工作目录的 `svbridge-config.json` 配置文件。如果文件不存在，首次运行时会自动创建。

你可以在启动服务时通过命令行参数来覆盖配置。这些参数也会更新配置文件。

- `-p [PORT]`, `--port [PORT]`：监听的端口（默认 8086）。
- `-b [BIND]`, `--bind [BIND]`：绑定的主机地址（默认 localhost）。
- `-k [KEY]`, `--key [KEY]`：指定 API 密钥。如果设空（默认），则允许使用任何密钥。
- `--auto-refresh`/`--no-auto-refresh`：启用/禁用后台自动刷新 Vertex 令牌（默认启用）。
- `--filter-model-names`/`--no-filter-model-names`：启用/禁用在 `/models` 接口过滤常见模型名称（默认启用）。
- `-h`, `--help`：显示帮助信息。

示例:
```bash
# 在端口 8848 公开运行，并设定密钥 'svb-cRztHvmE50'
python svbridge.py -p 8848 -b 0.0.0.0 -k svb-cRztHvmE50
```

## 开源协议

The Unlicense.

拿来爱干啥干啥，坏事了别来找我就好。uwu
