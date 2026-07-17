# uploads — 用户上传目录（运行时）

用户投稿附带的图片按 `submissions/<id>/` 存放，由后端投稿接口写入、
Nginx（生产）或后端静态挂载（本地）以 `/uploads` 对外服务。

- 内容为运行时产物，**不进 Git**（本 README 除外）；
- 删除投稿不会自动删除文件，磁盘清理见运维文档；
- 上传校验（类型/大小）在 `backend/routers/submissions.py`。
