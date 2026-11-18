# 客服质检系统 v4.0（老版本）

单文件 PyQt6 应用：导入会话记录 → 质检总览 → 双击看聊天 → 人工复核 → 导出。

这是拆包前的实现，评分与角色识别都写在 `app.py` 里。最新版见 `v5.2.0` tag，或直接看仓库主页的说明。

```bash
python -m pip install -r requirements.txt
python app.py
```

数据落在 `data/qc.db`（未入库）。
