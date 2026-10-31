"""The Next.js export stores segment prefetch data in a folder; the browser asks for it with a dot."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import ExportFiles


@pytest.mark.parametrize("with_404_page", [False, True])
def test_segment_prefetch_file_is_found_at_its_nested_path(tmp_path, with_404_page):
    (tmp_path / "advice" / "__next.advice").mkdir(parents=True)
    (tmp_path / "advice" / "__next.advice" / "__PAGE__.txt").write_text("rsc-data", encoding="utf-8")
    (tmp_path / "index.html").write_text("<h1>home</h1>", encoding="utf-8")
    if with_404_page:  # the real export has one; StaticFiles then serves it instead of raising
        (tmp_path / "404.html").write_text("<h1>not found</h1>", encoding="utf-8")
    app = FastAPI()
    app.mount("/", ExportFiles(directory=tmp_path, html=True))
    c = TestClient(app)

    r = c.get("/advice/__next.advice.__PAGE__.txt?_rsc=abc")
    assert r.status_code == 200 and r.text == "rsc-data"
    assert c.get("/").status_code == 200
    assert c.get("/advice/missing.txt").status_code == 404  # other missing files are still 404
    assert c.get("/advice/__next.nothing.__PAGE__.txt").status_code == 404
