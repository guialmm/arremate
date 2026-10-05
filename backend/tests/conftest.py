import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://arremate:arremate@localhost:5433/arremate_test"
)
os.environ["ENV"] = "test"

import io  # noqa: E402
import json  # noqa: E402
import zipfile  # noqa: E402
from collections.abc import Callable  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import models  # noqa: E402, F401
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.pncp.client import PncpClient  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def make_pdf(pages: list[str]) -> bytes:
    """A real, minimal PDF with one line of Helvetica text per page (ASCII only)."""
    objs: list[bytes] = []
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font_ref = 3 + 2 * len(pages)
    for i, page in enumerate(pages):
        lines = page.replace("(", r"\(").replace(")", r"\)").split("\n")
        ops = "BT /F1 11 Tf 14 TL 40 800 Td " + " ".join(f"({ln}) Tj T*" for ln in lines) + " ET"
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_ref} 0 R >> >> /Contents {4 + 2 * i} 0 R >>".encode()
        )
        objs.append(f"<< /Length {len(ops)} >>\nstream\n{ops}\nendstream".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for n, obj in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{n} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    out.write(b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets))
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return out.getvalue()


def make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


class FakePncp:
    """Routes requests to handlers by path; records every call."""

    def __init__(self):
        self.routes: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.calls: list[httpx.Request] = []

    def on(self, path: str, *responses: httpx.Response | Callable):
        """Successive calls get successive responses; the last one repeats."""
        queue = list(responses)

        def handler(request):
            r = queue.pop(0) if len(queue) > 1 else queue[0]
            return r(request) if callable(r) else r

        self.routes[path] = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        for path, handler in self.routes.items():
            if request.url.path.endswith(path) or str(request.url).startswith(path):
                return handler(request)
        return httpx.Response(404, json={"message": "not found"})


@pytest.fixture
def pncp():
    return FakePncp()


@pytest.fixture
async def client(pncp):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(pncp)) as http:
        c = PncpClient(http, base_url="https://pncp.test/api", max_attempts=3, sleep=fake_sleep)
        c.sleeps = sleeps
        yield c


@pytest.fixture(scope="session", autouse=True)
async def schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_db():
    yield
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def session():
    async with SessionLocal() as s:
        yield s
