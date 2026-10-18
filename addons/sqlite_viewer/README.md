# SQLite 只读网页查看器

这是原 SBC 离线包的增量组件，不包含数据库或 Python。所有页面资源随组件一起提供，运行时不访问互联网，也不需要 root 权限。

## 在目标机安装

将 `sbc-sqlite-viewer-addon.tar.gz` 和同名 `.sha256` 放到目标机，进入两个文件所在目录：

```bash
sha256sum -c sbc-sqlite-viewer-addon.tar.gz.sha256
tar -xzf sbc-sqlite-viewer-addon.tar.gz -C "$HOME/troubleshooting-sbc"
cd "$HOME/troubleshooting-sbc"
bash addons/sqlite_viewer/run.sh
```

在**目标机自身**的浏览器打开 `http://127.0.0.1:8002/`。原排障服务的 8001 端口可以同时运行。查看器只监听本机回环地址，数据库以只读模式打开，不提供修改或执行任意 SQL 的入口。

页面提供数据表和视图列表、字段类型、分页预览、单字段文字筛选，以及按字段分组的记录数、求和和平均值图表。表格单元格显示最长 4000 字符，图表最多显示 20 组。停止查看器时按 `Ctrl+C`。

若安装目录不是 `$HOME/troubleshooting-sbc`，将 `tar` 命令中的 `-C` 路径改为实际安装目录。如果需要改用别的数据库或端口，可执行：

```bash
bash addons/sqlite_viewer/run.sh --database /路径/数据库.db --port 8003
```

数据库应是静态文件；查看器使用 SQLite `immutable=1`，不会感知运行期间对同一数据库文件的写入。更新数据库后重启查看器。
