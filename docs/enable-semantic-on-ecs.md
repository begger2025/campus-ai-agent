# 公网服务器启用语义检索 · 组员安装交接说明

> **✅ 已完成并验证（2026-07-19）**：服务器已装齐 `torch 2.13.0` + `sentence-transformers 5.6.0`，
> 语义检索已启用并端到端实测通过——公网问「东校宿舍搬迁」命中「东校**区**宿舍搬迁」(13.7s)、
> 问「饭堂涨价」命中「食堂排队与价格反馈」(7.0s)。**线上与本地能力已完全一致，本文档转为存档。**
>
> 目标（已达成）：给线上服务器(8.134.250.107)装上 torch + 语义模型，让公网舆情助手和本地一样
> 能做模糊语义匹配。整理人：（AI 助手）· 2026-07-19

---

## 0. 一分钟看懂：你只需要做三件事

1. **装 torch + sentence-transformers**（唯一的难点：国内下 torch 要用镜像，见 §3）；
2. **重启后端** `systemctl restart campus-ai`；
3. **验证**：线上舆情助手问「东校宿舍搬迁」能出内容（见 §5）。

模型文件、向量文件、开关配置**我都已经准备好了**（见 §1），你不用管。

---

## 1. 我已经铺好的路（不用你再做）

| 已就位的东西 | 位置 | 说明 |
|------|------|------|
| **语义模型**（bge-small-zh-v1.5，93M） | `/root/.cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5` | 已上传，程序会**离线加载**，不用联网下 HuggingFace |
| **帖子向量文件** | `/opt/campus/campus-ai-agent-main/data/post_vectors.npz` | 已随部署上传，1358 条 × 512 维 |
| **2G swap** | `/swapfile`（已写入 `/etc/fstab`） | 防内存溢出的保险；扩容重启后**先确认它还在**（`swapon --show`），不在就重开一遍（§2） |
| **语义开关** | `.env` 里 `EMBEDDING_ENABLED` 没显式设 → **默认就是开的** | 所以只要 torch 和模型在，装完重启即自动生效，**不用改这个开关** |

> 一句话：**环境里就差 torch 和 sentence-transformers 两个 Python 包**，装上重启就通。

---

## 2. 装之前先确认（30 秒）

```bash
free -m                 # 确认内存/ swap；扩容后内存应 ≥ 3.4G
swapon --show           # 应看到 /swapfile 2G；若为空，执行下面三行重开 swap
```

若 swap 不在（扩容重启有时会掉），补一下（有 4G 内存其实也够，但留着更稳）：

```bash
swapon /swapfile 2>/dev/null || { mkswap /swapfile && swapon /swapfile; }
```

---

## 3. 装 torch + sentence-transformers（关键步骤）

**版本必须和本地一致**：`torch 2.12.0`、`sentence-transformers 5.5.1`。

> ⚠️ **最大的坑（我已经踩过）**：pytorch 官方源 `download.pytorch.org` 从国内服务器**必超时**
> （我实测卡在 `download-r2.pytorch.org` read timeout 反复重试）。**必须用国内镜像。**

进入项目目录，用**上海交大镜像**装 torch（CPU 版）：

```bash
cd /opt/campus/campus-ai-agent-main
./.venv/bin/pip install --timeout 120 torch --index-url https://mirror.sjtu.edu.cn/pytorch-wheels/cpu
```

- 若 SJTU 也慢/不通，换清华镜像：
  `--index-url https://mirrors.tuna.tsinghua.edu.cn/pytorch-wheels/cpu`
- **兜底方案（最稳）**：在**本地电脑**上把 torch 的 wheel 下好再传上去装——本地已装好 torch，
  执行 `pip download torch==2.12.0 --index-url https://download.pytorch.org/whl/cpu -d ./whl`，
  把 `./whl/torch-*.whl` scp 到服务器，再 `pip install /path/torch-xxx.whl`。

装完确认 torch 能导入：

```bash
./.venv/bin/python -c "import torch; print('torch', torch.__version__)"
```

再装 sentence-transformers（走**阿里云 PyPI 镜像**，服务器是阿里云 ECS，intra 网极快）：

```bash
./.venv/bin/pip install --timeout 120 "sentence-transformers==5.5.1" \
  -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
./.venv/bin/python -c "import sentence_transformers as s; print('st', s.__version__)"
```

> 装的过程放**后台跑 + 看日志**更稳（torch 约 190M，别让 SSH 断了就前功尽弃）：
> `nohup bash -c '上面几条命令' > /tmp/pip.log 2>&1 &` 然后 `tail -f /tmp/pip.log`。
> **千万别用** `pkill -f 'pip install'` 去杀进程——那条命令会把它自己也匹配杀掉（我踩过），
> 要杀就 `kill <具体pid>`。

---

## 4. 装完后：确认模型能离线加载 + 重启

先单独测一下模型加载（这一步会吃内存，是最考验的时刻，有 swap 兜底不怕）：

```bash
cd /opt/campus/campus-ai-agent-main
HF_HUB_OFFLINE=1 ./.venv/bin/python -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('BAAI/bge-small-zh-v1.5')
print('向量维度:', m.encode(['东校宿舍搬迁']).shape)
"
```

- 看到 `向量维度: (1, 512)` 就说明**模型离线加载成功**；
- 若它试图联网下载并卡住 → 加了 `HF_HUB_OFFLINE=1` 一般就走本地缓存；仍不行说明缓存路径不对，
  确认 `/root/.cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5/snapshots/*/model.safetensors` 在。

没问题就重启后端：

```bash
systemctl restart campus-ai
sleep 5
systemctl is-active campus-ai              # 应为 active
curl -s http://127.0.0.1:9000/api/ping     # 应返回 {"code":0,...}
journalctl -u campus-ai -n 30 --no-pager   # 看启动日志有没有 embedding 加载报错
```

> 重启后**第一次**加载 embedding 模型会慢几秒、吃一波内存（有 swap 不怕）。之后常驻。

---

## 5. 验证成功（决定性一步）

浏览器开**无痕窗口**登录 <http://8.134.250.107:9000>（admin / admin123456），进舆情助手问：

> **东校宿舍搬迁舆情简报**   ← 故意不带「区」字

- ✅ **成功**：能出完整简报（命中事件「东校区宿舍搬迁」）——说明语义匹配生效了；
- ❌ **还是「数据不足」**：说明 embedding 没真正启用，查 `journalctl -u campus-ai` 看有没有
  `sentence_transformers` 导入失败/模型加载失败的报错。

对照：装之前问这句会返回「数据为空」，装之后能命中——这就是本次改造的验收标准。

---

## 6. 出问题怎么退回去（一键回滚，别慌）

装挂了、或后端起不来、或内存告急，**一条命令退回现在的稳定状态**（轻量档、字面匹配，站点照常能用）：

```bash
# 在 .env 里把语义关掉
sed -i 's/^EMBEDDING_ENABLED=.*/EMBEDDING_ENABLED=false/' /opt/campus/campus-ai-agent-main/.env
grep -q '^EMBEDDING_ENABLED=' /opt/campus/campus-ai-agent-main/.env || echo 'EMBEDDING_ENABLED=false' >> /opt/campus/campus-ai-agent-main/.env
systemctl restart campus-ai
```

回滚后站点功能完整（就是模糊匹配没了，回到"话题词要字面对齐"的状态）。torch 装了也不占运行内存
（不 import 就不加载），留着无害。

---

## 7. ⚠️ 千万别碰的东西（会搞坏线上）

1. **别动 `.env` 里的 LLM 配置**。现在线上是这套（今天刚调好、验证过）：
   - `OPENAI_MODEL=glm-4-plus`（聊天主通道，智谱直连）
   - `EVENT_LLM_MODEL=glm-4-plus`（事件研判/预审）
   - `LLM_FALLBACK_MODEL=gpt-5.4`（备胎，别删）
   - 这些是我今天专门从卡死的 gpt-5.4 中转站切过来的，**动了聊天就会退回卡死状态**。

2. **改 `.env` 只在服务器上用 Linux 工具改**（`sed` / `vi` / python），
   **绝对不要**把服务器 `.env` 下载到 Windows 用记事本/PowerShell 编辑再传回去——
   会把 UTF-8 编码搞坏、中文注释乱码、甚至吞掉换行导致密钥失效（这个坑今天真出过一次）。

3. **别改 `EMBEDDING_ENABLED` 以外的 embedding 阈值**
   （`EMBEDDING_CLUSTER_THRESHOLD` 等是调好的，动了会影响聚类质量）。

4. 装包**只在** `/opt/campus/campus-ai-agent-main/.venv` 这个虚拟环境里装
   （用 `./.venv/bin/pip`），别装到系统 python。

---

## 8. 装完告诉我

装好验证通过后言语一声，我会：
- 把演示脚本/教师指南里"话题词必须字面对齐"的限制说明去掉（因为公网现在能模糊匹配了）；
- 更新交付物文档里"线上轻量档"的口径。

---

*本文基于 2026-07-19 我本人在该服务器上的实测（含踩到的 pytorch CDN 超时、pkill 自杀、.env 编码
三个坑）整理，命令均可直接复制执行。*
