# 基座模型调用说明

项目通过 `llm` 包统一选择模型、发送请求和规范化返回结果。业务代码应调用 `llm.chat_reply` 或 `llm.chat_reply_stream`，不要自行创建厂商 SDK 客户端。

## 两层配置

- **服务商连接（provider）**决定调用协议、API 根地址和密钥来源。内置连接有 `aliyun`、`openai`、`gemini`；管理员可以在模型管理页新增 `openai_chat` 兼容连接。自定义连接存于 `data/model_profiles.sqlite3` 的 `provider_connections` 表。
- **模型入口（profile）**引用一个 provider，指定模型 ID 和可选的生成参数。一个 provider 可对应多个模型入口。已有入口的 provider、模型 ID 和基础地址保持只读，修改时复制为新入口。

自定义连接的 `api_key_env` 只保存**环境变量名称**，不保存 API Key。先在服务端环境或项目 `.env` 设置密钥，例如 `DEEPSEEK_API_KEY=...`，再新增连接并填写 `DEEPSEEK_API_KEY`。调用时才从环境读取该值。项目的 `.env` 只供本地服务端使用，不应提交到版本库。

## 调用路径

```text
业务模块 → llm.chat_reply / chat_reply_stream
         → llm.config.resolve_model_runtime（读取模型入口）
         → llm.providers.registry.create_provider（解析连接）
         → 协议适配器 → 厂商 API
```

`llm/providers/openai_provider.py` 执行 OpenAI Chat Completions 协议，当前也服务于阿里云百炼及自定义兼容连接。`llm/providers/gemini_provider.py` 与 `gemini_impl.py` 使用 Google GenAI 原生 SDK。两者都返回项目内部统一的 `content`、`tool_calls`、可选 `usage` 字段；流式调用产生 `chunk` 和最终 `done` 事件。

```python
from llm import chat_reply, chat_reply_stream

reply = chat_reply(
    [{"role": "user", "content": "你好"}],
    profile_name="gemini_default",
)
print(reply["content"])

for event in chat_reply_stream(
    [{"role": "user", "content": "你好"}],
    profile_name="gemini_default",
):
    if event["type"] == "chunk":
        print(event["content"], end="", flush=True)
```

不指定 `profile_name` 时，使用 `MODEL_PROFILE` 环境变量或当前默认模型入口。生成参数通常留空并由模型决定；入口中显式设置的参数会由 `llm/factory.py` 传给适配器。工具调用采用统一的 OpenAI 风格函数声明，由 Gemini 适配器转换为原生格式。

## 在页面新增服务商

1. 在“模型管理”选择“新增服务商连接”，填连接 ID、显示名称、API 根地址和 API Key 的环境变量名。当前页面创建的连接使用 `openai_chat` 协议。远程地址须为 HTTPS；本机 `localhost` 可用 HTTP。
2. 设置密钥环境变量并重启服务，使进程读到新的变量。
3. 新建模型入口，选择该连接，填准确的模型 ID。模型目录来自上游 `models.list`；上游不提供目录或查询失败时，可以手填模型 ID。
4. 使用“测试模型调用”验证该模型实际返回文本。此操作执行一次简短推理，不只是检查 API Key 或模型目录。

例如 DeepSeek 官方 OpenAI 兼容地址可填 `https://api.deepseek.com`；模型 ID 与密钥必须以所使用账户的当前接口为准。请将完整 **API 根地址** 填入 `base_url`，不要再拼接 `/chat/completions`。

## 扩展协议

如新服务商兼容 OpenAI Chat Completions，新增连接即可。若需要原生协议，在 `llm/providers/` 实现 `LLMProvider` 的 `list_models`、`get_model_capabilities`、`chat`、`chat_stream`，并通过 `llm/providers/registry.py` 注册。目录发现与能力查询不能代替实际调用验证；支持工具调用的智能体还应验证流式工具调用。

`llm/model_management.py` 实现模型目录、能力读取和点对点测试。`llm/call_tracking.py` 统一模型调用进度文案。旧独立智能体仍消费 OpenAI SDK 原始响应对象，客户端创建和原始 SDK 请求集中在 `llm/legacy.py`；后续改造这些智能体时应切换到统一的 `chat_reply` 接口。
