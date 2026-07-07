"""Print campus.db summary to console. Usage: python scripts/view_db.py"""
import sqlite3
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "campus.db"


def export_markdown(conn: sqlite3.Connection, out: Path) -> None:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM raw_posts")
    total = cur.fetchone()[0]
    lines = [
        "# campus.db 导出（只读预览）",
        "",
        f"源文件: `{DB}`",
        f"raw_posts 共 **{total}** 条",
        "",
    ]
    cur.execute(
        """
        SELECT id, platform, title, author, publish_time, crawl_time, url, content
        FROM raw_posts ORDER BY id DESC
        """
    )
    for row in cur.fetchall():
        lines.append(f"## #{row['id']} [{row['platform']}] {row['title']}")
        lines.append("")
        lines.append(f"- 作者: {row['author']}")
        lines.append(f"- 发布时间: {row['publish_time']}")
        lines.append(f"- 爬取时间: {row['crawl_time']}")
        if row["url"]:
            lines.append(f"- 链接: {row['url']}")
        content = (row["content"] or "").strip()
        if content:
            lines.append("")
            lines.append("```")
            lines.append(content[:500] + ("..." if len(content) > 500 else ""))
            lines.append("```")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Exported: {out}")


def main() -> None:
    if not DB.exists():
        print(f"Database not found: {DB}")
        sys.exit(1)

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]

    print(f"Database: {DB}")
    print("=" * 60)
    print("TABLES")
    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM [{t}]")
        print(f"  {t}: {cur.fetchone()[0]} rows")

    if "raw_posts" in tables:
        print()
        print("raw_posts BY platform")
        cur.execute("SELECT platform, COUNT(*) AS c FROM raw_posts GROUP BY platform")
        for r in cur.fetchall():
            print(f"  {r['platform']}: {r['c']}")

        print()
        print("raw_posts (latest 20)")
        print("-" * 60)
        cur.execute(
            """
            SELECT id, platform, title, author, url, publish_time, crawl_time
            FROM raw_posts
            ORDER BY id DESC
            LIMIT 20
            """
        )
        for r in cur.fetchall():
            title = (r["title"] or "")[:60]
            print(f"#{r['id']} [{r['platform']}] {title}")
            print(f"    author={r['author']}  publish={r['publish_time']}  crawl={r['crawl_time']}")
            if r["url"]:
                print(f"    {r['url']}")
            print()

    export = ROOT / "data" / "campus_db_preview.md"
    export_markdown(conn, export)

    conn.close()


if __name__ == "__main__":
    main()
