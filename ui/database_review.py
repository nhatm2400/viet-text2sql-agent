"""Local read-only browser for the evaluation snapshot; no LLM or review mutations."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "data/benchmark_v2_ready"
DATABASE = PACKAGE / "snapshot.sqlite"
ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION}
ALLOWED.add(sqlite3.SQLITE_RECURSIVE)


def read_query(sql: str, params=(), database: Path = DATABASE):
    """Bounded SELECT-only execution, including protection against ATTACH and PRAGMA."""
    conn = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.set_authorizer(
            lambda action, *_: sqlite3.SQLITE_OK if action in ALLOWED else sqlite3.SQLITE_DENY
        )
        deadline = time.monotonic() + 5
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        cursor = conn.execute(sql, params)
        rows = cursor.fetchmany(501)
        return [c[0] for c in cursor.description], rows[:500], len(rows) > 500
    finally:
        conn.close()


def display(sql: str, params=()):
    try:
        columns, rows, truncated = read_query(sql, params)
    except sqlite3.Error as err:
        st.error(f"Không chạy được truy vấn: {err}")
        st.caption("Chỉ hỗ trợ truy vấn đọc dữ liệu; mỗi truy vấn tối đa 5 giây.")
        return
    st.dataframe(pd.DataFrame.from_records(rows, columns=columns), hide_index=True)
    if truncated:
        st.info("Đang hiển thị 500 dòng đầu. Thêm điều kiện WHERE để xem phần cần kiểm tra.")
    else:
        st.caption(f"Kết quả: {len(rows):,} dòng.")


def main():
    st.set_page_config(page_title="Xem database và kiểm tra đáp án", layout="wide")
    st.title("Xem database và kiểm tra đáp án")
    st.caption("Dữ liệu mô phỏng dùng cho eval • Chỉ đọc • Không gọi AI hay API trả phí")
    if not DATABASE.exists():
        st.error(f"Chưa tìm thấy database: {DATABASE}")
        st.stop()
    st.info("Bắt đầu ở tab Xem bảng: chọn customers để xem khách hàng, regions để xem các miền.")
    browse, review, sql_tab = st.tabs(["1. Xem bảng", "2. Xem đáp án mẫu", "3. Tự chạy SELECT"])
    with browse:
        _, tables, _ = read_query(
            "SELECT name, sql FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        names = [r[0] for r in tables]
        chosen = st.selectbox("Bảng dữ liệu", names, index=names.index("customers"))
        quoted = '"' + chosen.replace('"', '""') + '"'
        _, counts, _ = read_query(f"SELECT COUNT(*) FROM {quoted}")
        st.write(f"Bảng **{chosen}** có **{counts[0][0]:,} dòng**. Bên dưới là 100 dòng đầu.")
        display(f"SELECT * FROM {quoted} LIMIT 100")
        with st.expander("Cấu trúc và khóa của bảng"):
            st.code(dict(tables)[chosen], language="sql")
    with review:
        st.write("Đọc câu hỏi, xem cách SQL tính đáp án, rồi bấm chạy để xem kết quả thật.")
        st.caption(
            "Kết quả chạy được chưa chứng minh đáp án đúng nghĩa. Trang này không tự duyệt câu hỏi."
        )
        items = json.loads((PACKAGE / "questions.json").read_text(encoding="utf-8"))
        split = st.radio("Bộ câu hỏi", ["dev", "test"], horizontal=True)
        candidates = [item for item in items if item["split"] == split]
        index = st.selectbox(
            "Câu cần kiểm tra",
            range(len(candidates)),
            format_func=lambda i: f"{i + 1}. {candidates[i]['id']}",
        )
        item = candidates[index]
        st.subheader(item["question_vi"])
        st.code(item["gold_sql"], language="sql")
        st.write("Kiểm tra: đúng bảng/cột? Đúng bộ lọc và thời gian? JOIN có đếm trùng không?")
        if st.button("Chạy SQL đáp án mẫu", type="primary"):
            display(item["gold_sql"])
    with sql_tab:
        st.write("Bạn có thể sửa truy vấn dưới đây rồi bấm Chạy SELECT để đối chiếu số liệu.")
        with st.form("query"):
            sql = st.text_area(
                "SQL chỉ đọc",
                "SELECT r.region_code, c.status, COUNT(*) AS customer_count\n"
                "FROM customers c JOIN regions r ON r.region_id = c.region_id\n"
                "GROUP BY r.region_code, c.status\nORDER BY r.region_code, c.status;",
                height=180,
            )
            if st.form_submit_button("Chạy SELECT"):
                display(sql)
    with st.expander("Database đang mở"):
        st.code(str(DATABASE), language=None)


if __name__ == "__main__":
    main()
