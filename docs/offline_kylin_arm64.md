# 麒麟 ARM64 离线部署（精简 SBC 版）

此版本只交付天基承载网故障排查、报告、模型管理和网页界面。模型本身运行在内网 OpenAI Chat Completions 兼容服务上，不随包分发。目标机安装时不需要互联网、Node.js、编译器或系统 Python 3.12；包内带有 CPython 3.12 和全部 Python wheels。

## 构建机要求

在**与目标机同一麒麟发行版/版本的 Linux aarch64** 机器上构建，或使用相同系统镜像。至少核对 `uname -m`、`cat /etc/os-release`、`getconf GNU_LIBC_VERSION`；构建机的 glibc 不应比目标机新。构建机可联网，需有 C 编译器、make、Python 3.12 编译所需的 OpenSSL/SQLite/zlib/bzip2/xz/libffi 开发库，以及官方 CPython 3.12.x 源码压缩包。安装机不需要这些开发工具，但仍使用该麒麟版本自带的系统 C/加密/数据库共享库；安装脚本会校验 Python 扩展是否能加载。

1. 在开发机执行 `cd frontend && npm ci && npm run build`，不要设置 `VITE_API_BASE_URL`。构建产物必须是 `frontend/dist`，其中不能出现 `http://127.0.0.1:8001`。
2. 将当前项目代码、`frontend/dist`、`data/sbc_simulation_20260808.db` 和官方 Python 源码包带到联网的麒麟 ARM64 构建机；**不要复制开发机 `.env` 或用户数据库**。注意 `frontend/dist` 和 `data/` 被 Git 忽略，单纯 `git clone` 不会带上它们。
3. 执行：

```bash
CPYTHON_VERSION=3.12.x \
CPYTHON_TARBALL=/path/to/Python-3.12.x.tar.xz \
CPYTHON_SHA256=<官方源码包的SHA256> \
bash scripts/offline/build_arm64.sh
```

将命令中的 `x` 和 SHA256 换成所选正式版的真实值。脚本从源码安装独立 Python 到包内，下载并验证 Linux aarch64 wheels，生成完整的依赖锁文件，备份仿真 SQLite 库，然后输出 `offline-packages/troubleshooting-sbc-kylin-arm64-py3.12.x.tar.gz` 和 `.sha256`。若缺少二进制 wheel，构建直接失败，不会让目标机离线编译依赖。不要从 macOS 复制 `.venv` 或 wheels。

## 离线安装与运行

把两个交付文件拷贝到目标机，在目标机上校验 SHA256 后解压并安装：

```bash
sha256sum -c troubleshooting-sbc-kylin-arm64-py3.12.x.tar.gz.sha256
mkdir troubleshooting-sbc
tar -xzf troubleshooting-sbc-kylin-arm64-py3.12.x.tar.gz -C troubleshooting-sbc
cd troubleshooting-sbc
./install.sh
```

安装程序只从包内 `wheelhouse` 安装，不请求网络；成功后编辑权限为 `0600` 的 `.env`，设置独一无二的 `ADMIN_PASSWORD`、`SUPER_ADMIN_PASSWORD`，并填写 `INTRANET_LLM_BASE_URL`（如 `http://10.0.0.8:8000/v1`）、`INTRANET_LLM_MODEL` 和 `INTRANET_LLM_API_KEY`。无鉴权服务可填一个非空占位 Key。首次启动时会以这些值建立默认模型入口。随后运行 `./run.sh`，浏览器访问 `http://<目标机内网IP>:8001/`。`GET /api/apps` 与页面共用此端口。可用 `./.venv/bin/python -m pip check` 再次核对依赖。

请先把压缩包解压到最终安装目录再执行 `install.sh`；Python 虚拟环境中的解释器路径不保证在安装后搬迁目录仍可用。若离线安装中断，修复原因后可重跑 `install.sh`。

默认入口已经使用内网 OpenAI 兼容协议。后续也可在“模型管理”中新增 provider：API 根地址填内网服务的 `/v1` 根路径，Key 环境变量填另一个保存在 `.env` 中的变量名。服务至少应支持 `POST /v1/chat/completions`，并正确实现排障流程使用的工具调用；若支持 `/v1/models`，页面可自动列出模型，否则可手工录入模型名。测试连接会实际请求模型。`ALLOW_INSECURE_LLM_HTTP=1` 仅为可信内网的 HTTP 服务开启；若服务有 HTTPS，应改为 `0`。

## 交付边界与体积

交付包包含 `backend/`、`llm/`、两个 SBC skill、构建好的前端、32 MB 左右的仿真库、Python 3.12、离线 wheels 和安装脚本。它不含开发依赖、Node/npm、绘图/OCR 大包、`knowledge/`、用户会话、账号、checkpoint、历史输出或任何实际 API Key。`requirements-offline-arm64.txt` 是最小直接依赖；`requirements-offline-arm64.lock` 是构建时解析得到的完整依赖。

此前基于 macOS 已安装包的预估为压缩包约 **100–180 MB**、安装后约 **230–330 MB**；真实数值以麒麟 ARM64 构建脚本打印的 `du` 为准。CPython 源码安装的标准库大小和 aarch64 wheel 大小可能使实际包超出这个区间。若需要恢复历史会话或增加通用绘图、OCR、Gemini 等功能，应另行迁移数据并扩展对应依赖包，不属于本精简版。

运行目录中的 `data/`、`outputs/`、`.env` 必须可写且应持久化备份；不要在升级时直接覆盖它们。安装包不是完全静态链接的单一可执行文件，跨麒麟版本或跨 glibc 版本时需要重新构建与验证。
