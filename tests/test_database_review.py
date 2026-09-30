import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

from ui.database_review import DATABASE, read_query


def test_browser_blocks_mutations_and_limits_results(tmp_path):
    database = tmp_path / "test.sqlite"
    conn = sqlite3.connect(database)
    conn.execute("CREATE TABLE sample (n INTEGER)")
    conn.executemany("INSERT INTO sample VALUES (?)", [(i,) for i in range(600)])
    conn.commit()
    conn.close()
    columns, rows, truncated = read_query("SELECT n FROM sample", database=database)
    assert columns == ["n"] and len(rows) == 500 and truncated
    for sql in [
        "DELETE FROM sample",
        "DROP TABLE sample",
        "PRAGMA query_only=OFF",
        "ATTACH DATABASE ':memory:' AS other",
    ]:
        with pytest.raises(sqlite3.DatabaseError):
            read_query(sql, database=database)
    assert read_query("SELECT COUNT(*) FROM sample", database=database)[1] == [(600,)]


@pytest.mark.skipif(not DATABASE.exists(), reason="Local benchmark snapshot is not installed")
def test_review_page_browse_and_execute():
    app = AppTest.from_file("ui/database_review.py").run(timeout=15)
    assert not app.exception
    assert app.selectbox[0].value == "customers"
    app.button[0].click().run(timeout=15)
    assert not app.exception
    assert any(frame.value.iloc[0, 0] == 1354 for frame in app.dataframe if len(frame.value) == 1)
    app.button[1].click().run(timeout=15)
    assert not app.exception
