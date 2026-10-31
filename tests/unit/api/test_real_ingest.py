from app.api.bootstrap import real_ingest


def test_a_second_file_with_the_same_content_is_not_called_a_duplicate(tmp_path):
    results = []
    for stem in ("a" * 32, "b" * 32):  # two uploads of identical content
        path = tmp_path / f"{stem}.csv"
        path.write_text("name,value\nrevenue,100\nprofit,20\n")
        results.append(real_ingest(str(path)))
    assert [r.status for r in results] == ["success", "success"]
    assert all(len(r.chunks) == 2 for r in results) 