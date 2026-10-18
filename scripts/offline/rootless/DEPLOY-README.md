# SBC 麒麟桌面 V10 SP1 2303 ARM64 离线包（普通用户安装）

此包在 Ubuntu 20.04 ARM64（glibc 2.31）容器中构建，用于麒麟桌面 V10 SP1 2303 ARM64。它包含 Python 3.12、离线 wheels、所需的非 glibc 共享库、SBC 后端、两个 SBC skill、前端成品和仿真数据库。模型服务不在包内，需由目标内网提供 OpenAI Chat Completions 兼容接口。

## 安装

以普通用户在最终安装目录执行，不需要 `sudo`：

```bash
sha256sum -c troubleshooting-sbc-kylin-v10sp1-2303-arm64-py3.12.14-rootless-minimal-candidate.tar.gz.sha256
mkdir -p "$HOME/troubleshooting-sbc"
tar -xzf troubleshooting-sbc-kylin-v10sp1-2303-arm64-py3.12.14-rootless-minimal-candidate.tar.gz -C "$HOME/troubleshooting-sbc"
cd "$HOME/troubleshooting-sbc"
./install.sh
```

编辑 `.env`，设置独一无二的 `ADMIN_PASSWORD`、`SUPER_ADMIN_PASSWORD`，以及 `INTRANET_LLM_BASE_URL`、`INTRANET_LLM_MODEL`、`INTRANET_LLM_API_KEY`。然后执行 `./run.sh`。默认端口为 8001。安装后不要移动整个目录，Python 虚拟环境记录了绝对路径。

## 目标机验收

```bash
uname -m
getconf GNU_LIBC_VERSION
export LD_LIBRARY_PATH="$PWD/runtime-libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
./.venv/bin/python -m pip check
./.venv/bin/python -c 'import ssl, sqlite3; print(ssl.OPENSSL_VERSION, sqlite3.sqlite_version)'
```

目标应为 `aarch64`、`glibc 2.31`。

此包在无网络、非 root 的 ARM64 Ubuntu 20.04 容器中做过安装预检。麒麟的系统策略、CPU 具体型号和内网模型兼容性仍需在目标机验证。运行目录的 `.env`、`data/`、`outputs/` 应保持可写，并在升级前备份。
