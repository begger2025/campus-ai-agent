"""用户投稿（参与感 V2）：投稿是线索，前置审核，通过才进数据管线。

## 契约

- 投稿 = 第一方发布的新内容主张 → **前置审核**（与评论的后置管控相反：
  诽谤/虚假的风险不同量级）；驳回必填理由（投稿人有权知道为什么）。
- 通过 → 写 raw_posts(platform='campus', external_id='sub:<id>')——第三个
  数据入口，与爬取数据同等待遇走既有管线；绝不直接造事件、不自动挂事件。
- 图片三道闸：扩展名白名单 + 魔数嗅探（防改后缀）+ UUID 重命名（防路径
  穿越）；投稿引用的路径必须是本系统上传产物。
- LLM 只吃文字：正文必填，图片是给人看的证据附件。
"""

from __future__ import annotations

import io
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.admin_models import User
from backend.database import Base, get_db
from backend.main import app
from backend.models import RawPost, UserSubmission
from backend.services.auth_service import get_current_user, require_admin
from backend.services.submission_service import reset_submission_rate_limit


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        def override_get_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        self.user = User(id=7, username="stu01", role="user")
        admin = User(id=1, username="admin", role="admin")
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[require_admin] = lambda: admin
        self.addCleanup(app.dependency_overrides.clear)
        reset_submission_rate_limit()
        self.addCleanup(reset_submission_rate_limit)
        self.client = TestClient(app)
        self.uploaded: list[Path] = []
        self.addCleanup(self._cleanup_files)

    def _cleanup_files(self) -> None:
        from backend.services.submission_service import ROOT

        for path in self.uploaded:
            try:
                (ROOT / path).unlink(missing_ok=True)
            except OSError:
                pass

    def _upload(self, filename="pic.png", data=PNG_BYTES):
        r = self.client.post(
            "/api/submissions/uploads", files={"file": (filename, io.BytesIO(data), "image/png")}
        )
        if r.status_code == 200:
            self.uploaded.append(Path(r.json()["data"]["path"]))
        return r

    def _submit(self, **overrides):
        reset_submission_rate_limit()
        body = {"title": "东门夜市占道经营", "content": "连续一周晚上占用消防通道，附照片。", "images": []}
        body.update(overrides)
        return self.client.post("/api/submissions", json=body)


class UploadTests(_Fixture):
    def test_valid_png_uploads_and_gets_a_relative_path(self) -> None:
        r = self._upload()

        self.assertEqual(r.status_code, 200)
        path = r.json()["data"]["path"]
        self.assertRegex(path, r"^uploads/submissions/\d{6}/[a-f0-9]{32}\.png$", "UUID 重命名+月份目录")

    def test_renamed_executable_is_rejected_by_magic_sniff(self) -> None:
        r = self._upload(filename="evil.png", data=b"MZ\x90\x00" + b"\x00" * 32)

        self.assertEqual(r.status_code, 400, "魔数嗅探：内容说了算，后缀只是参考")

    def test_disallowed_extension_is_rejected(self) -> None:
        r = self._upload(filename="movie.mp4", data=b"\x00" * 16)

        self.assertEqual(r.status_code, 400, "V2 图片先行，视频缓行")

    def test_oversize_image_is_rejected(self) -> None:
        r = self._upload(data=PNG_BYTES + b"\x00" * (5 * 1024 * 1024))

        self.assertEqual(r.status_code, 400)


class CreateSubmissionTests(_Fixture):
    def test_submission_with_uploaded_image(self) -> None:
        path = self._upload().json()["data"]["path"]

        r = self._submit(images=[path])

        self.assertEqual(r.status_code, 200)
        data = r.json()["data"]
        self.assertEqual(data["status"], "pending", "前置审核：投稿默认待审")
        self.assertEqual(data["images"], [path])

    def test_blank_content_is_rejected(self) -> None:
        r = self._submit(content="   ")

        self.assertEqual(r.status_code, 400, "LLM 只吃文字——正文必填，图片是附件")

    def test_path_traversal_in_images_is_rejected(self) -> None:
        for evil in ["../../.env", "uploads/submissions/../../.env", "C:/windows/win.ini"]:
            with self.subTest(path=evil):
                r = self._submit(images=[evil])
                self.assertEqual(r.status_code, 400)

    def test_referencing_a_nonexistent_upload_is_rejected(self) -> None:
        r = self._submit(images=["uploads/submissions/202607/" + "a" * 32 + ".png"])

        self.assertEqual(r.status_code, 400)

    def test_rate_limit_blocks_rapid_submissions(self) -> None:
        first = self.client.post("/api/submissions", json={"title": "一", "content": "内容一"})
        second = self.client.post("/api/submissions", json={"title": "二", "content": "内容二"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_mine_lists_only_own_rows(self) -> None:
        self._submit()
        db = self.session_factory()
        db.add(UserSubmission(user_id=999, username="别人", title="别人的", content="x"))
        db.commit()
        db.close()

        data = self.client.get("/api/submissions/mine").json()["data"]

        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["username"], "stu01")


class ReviewTests(_Fixture):
    def _pending_id(self, **overrides) -> int:
        return self._submit(**overrides).json()["data"]["id"]

    def test_approve_writes_a_campus_raw_post(self) -> None:
        path = self._upload().json()["data"]["path"]
        sid = self._pending_id(images=[path])

        r = self.client.patch(f"/api/admin/submissions/{sid}", json={"status": "approved"})

        self.assertEqual(r.status_code, 200)
        data = r.json()["data"]
        self.assertEqual(data["status"], "approved")
        db = self.session_factory()
        raw = db.query(RawPost).filter(RawPost.id == data["raw_post_id"]).first()
        db.close()
        self.assertEqual(raw.platform, "campus", "第三个数据入口：站内投稿")
        self.assertEqual(raw.external_id, f"sub:{sid}", "(platform, external_id) 唯一约束 = 幂等挡板")
        self.assertIn(path, raw.images_json, "图片路径随行带进 raw_posts（给人看的证据附件）")
        self.assertEqual(raw.title, "东门夜市占道经营")

    def test_reject_requires_a_reason(self) -> None:
        sid = self._pending_id()

        r = self.client.patch(f"/api/admin/submissions/{sid}", json={"status": "rejected"})

        self.assertEqual(r.status_code, 400, "驳回必填理由——投稿人有权知道为什么")

    def test_a_submission_is_reviewed_only_once(self) -> None:
        sid = self._pending_id()
        self.client.patch(f"/api/admin/submissions/{sid}", json={"status": "approved"})

        again = self.client.patch(f"/api/admin/submissions/{sid}", json={"status": "approved"})

        self.assertEqual(again.status_code, 409)
        db = self.session_factory()
        raws = db.query(RawPost).filter(RawPost.external_id == f"sub:{sid}").count()
        db.close()
        self.assertEqual(raws, 1, "重复审批不许写出第二条 raw_post")

    def test_guest_cannot_submit(self) -> None:
        app.dependency_overrides[get_current_user] = lambda: None

        r = self.client.post("/api/submissions", json={"title": "游客", "content": "投稿"})

        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
