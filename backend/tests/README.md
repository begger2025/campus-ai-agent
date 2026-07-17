# backend/tests — 后端测试（109 文件 / 约 1180 用例）

标准库 `unittest`，覆盖接口、服务、核心算法与对抗性场景。

## 运行

```bash
# 全量（项目根，约 60 秒）
.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -q

# 单文件
.venv\Scripts\python.exe -m unittest backend.tests.test_intent_router -v

# 三套测试 + 前端构建一起跑
.\check.ps1
```

## 铁律

1. **零网络依赖**：所有 LLM/HTTP 调用在测试中打桩（stub/monkeypatch），CI 无密钥可跑。
   新测试若需要真实网络，说明设计错了——把外部调用做成可注入。
2. **不碰共享库**：测试一律用临时 SQLite（`tmp_path`/内存库），与开发库、共享 MySQL 隔离。
3. **测行为不测桩**：断言的是被测代码的输出/副作用，不是 mock 被调了几次。

## 命名与组织

- 文件 `test_<被测模块或场景>.py`，与被测对象一一对应（如 `test_intent_router.py`）；
- 场景化测试直接以场景命名（如 `test_chat_stream_route.py`、对抗性注入类）；
- 全部平铺在本目录——按域拆子目录属于后续演进（见交付物 6 的规划章节），
  当前用文件名前缀（`test_chat_*` / `test_event_*` / `test_admin_*`）即可定位一族。

## 修 bug 的约定

先写复现失败的测试，看它红，再修代码让它绿（TDD）——测试即回归保险。
