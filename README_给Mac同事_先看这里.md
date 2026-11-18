# 给 Mac 同事的打包说明（先看这里）

这个文件夹是「全量自动化客服质检系统」的**源码工具包**。在 Mac 上只需要做一次构建，之后就能得到可以直接双击运行的 `.app`（同事使用不需要装 Python）。

## 一、在 Mac 上构建（只做一次，约 5 分钟）

1. 解压这个 zip，得到 `客服质检系统_源码包` 文件夹；
2. 打开「终端」，把文件夹拖进终端窗口，执行：
   ```bash
   cd 拖进来的文件夹路径
   chmod +x build_macos.command start_mac.command
   ```
3. 双击 `build_macos.command`（或终端执行 `bash build_macos.command`）；
   - 首次会自动安装依赖（需要联网，PyQt6 约 60~100MB）；
   - 然后自动打包，看到 `[DONE]` 即成功；
4. 产物在 `dist/` 里：
   - `全量自动化客服质检系统.app` ← **双击即可用**
   - `全量自动化客服质检系统_macOS.zip` ← 发给其他同事的最终文件

> 前提：Mac 上有 python3（终端执行 `xcode-select --install` 即可获得）且能联网。

## 二、同事怎么用（不需要装 Python）

1. 收到 `全量自动化客服质检系统_macOS.zip`，解压；
2. 里面是 `dist` 文件夹：`.app` + `config/` + `docs/` + `data/`；
3. **整个文件夹一起**放到桌面或「应用程序」（不要只挪 .app，配置和数据在同级）；
4. 双击 `全量自动化客服质检系统.app`。

首次打开若提示“无法验证开发者”：右键 .app → 打开；或终端执行：
```bash
xattr -dr com.apple.quarantine 全量自动化客服质检系统.app
```

## 三、注意

- 本包**不含**你的业务数据（`data/` 已剔除），会话需要同事自己导入；
- 本包**不含** AI 密钥，打开后到「智能设置」填接口地址/模型/密钥；
- 构建机器是 Apple Silicon 还是 Intel，会影响产物架构；给 Intel Mac 用时建议在 Intel 机器上构建，或在 Rosetta 下测试。
- 详细说明见 `docs/macOS_使用说明.md`。
