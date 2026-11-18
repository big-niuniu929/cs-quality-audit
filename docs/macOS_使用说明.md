# macOS 使用与打包说明

> 系统：**全量自动化客服质检系统（爆单一铲）** v4.2.0
> 目标：同事 **不用安装 Python**，解压后双击即用。

## 一、给同事（使用方）

1. 找 IT/你拿到 `全量自动化客服质检系统_macOS.zip`；
2. 解压，得到 `dist` 文件夹（里面有 `全量自动化客服质检系统.app`、`config/`、`docs/`、`data/`）；
3. **把整个文件夹**放到「应用程序」或桌面任意位置（不要只移动 .app，配置和数据在同级目录）；
4. 双击 `全量自动化客服质检系统.app` 即可启动，不需要安装 Python 或任何依赖。

### 首次打开被拦截怎么办

macOS 可能提示「无法验证开发者」：

- 方法一：在 .app 上 **右键 → 打开** → 再点「打开」；
- 方法二：终端执行
  ```bash
  xattr -dr com.apple.quarantine "/路径/全量自动化客服质检系统.app"
  ```

### 数据存在哪

- 会话库：`data/qc.db`
- 聊天历史：`data/copilot_history.json`
- 配置：`config/`
- 都跟 .app 在同一个文件夹里，整个文件夹一起备份即可。

## 二、给维护者（构建方）

macOS 的 `.app` 必须在 Mac 上编译（PyInstaller 不支持从 Windows 交叉编译），步骤只有一步：

1. 把项目文件夹拷到 Mac；
2. 双击 `build_macos.command`（首次若提示无法执行，右键 → 打开，或终端 `chmod +x *.command`）；
3. 脚本会自动安装依赖 → PyInstaller 打包 → 复制配置/说明书 → 生成
   - `dist/全量自动化客服质检系统.app`
   - `全量自动化客服质检系统_macOS.zip`（这就是发给同事的文件）。

构建机要求：macOS 12+、联网（装 PyQt6 与 PyInstaller）、python3（`xcode-select --install` 即可）。
Apple Silicon 与 Intel 均可构建，产物跟随构建机架构。

## 三、常见问题

| 现象 | 处理 |
|---|---|
| 双击无反应 | 看是否只拷了 .app 没带 config；右键打开一次；终端运行 .app/Contents/MacOS/全量自动化客服质检系统 看报错 |
| 提示缺 config | 确认整个文件夹一起拷贝（.app 与 config 同级） |
| AI 回答失败 | 「智能设置」填接口地址/模型/密钥；或检查公司网络 |
| 想改端口/数据目录 | 设置环境变量 `QC_APP_DIR` 指向数据根目录 |

## 零、免安装绿色包（推荐，同事什么都不用装）

交付文件：`全量自动化客服质检系统_macOS_免安装.zip`（约 73MB，仅 Apple Silicon）

1. 双击解压，得到 `全量自动化客服质检系统` 文件夹（**整个文件夹**使用，不要只拷里面的 .app）；
2. 双击「启动系统.command」；或右键「2-双击启动.app」→ 打开；
3. 首次被系统拦截时：右键「2-双击启动.app」→ 打开 → 再点“打开”；或在终端执行
   `xattr -dr com.apple.quarantine "全量自动化客服质检系统"`；
4. 包里已内置 Python 3.12 与 PyQt6，**不需要安装 Python、不需要联网装依赖**。

注意：
- 仅支持 Apple Silicon（M1/M2/M3/M4）；Intel Mac 请用“源码构建”方式在该机器上生成。
- 如启动失败：终端进入包目录执行 `./python/bin/python3 app.py` 看报错，把最后几行发管理员。
- 数据在 `data/`，配置在 `config/`，都在包内，整个文件夹备份即可。
