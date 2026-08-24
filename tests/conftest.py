from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from apps.booking_api.main import app as booking_app
from apps.booking_api.main import reset_store
from apps.voice_agent.backend_client import BackendClient
from apps.voice_agent.dialog_engine import DialogEngine
from apps.voice_agent.extractor import HeuristicExtractor
from apps.voice_agent.rag import KnowledgeRetriever

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


@pytest.fixture
def today():
    return datetime.now(VN_TZ).date()


@pytest.fixture
def tomorrow(today):
    return today + timedelta(days=1)


@pytest.fixture(autouse=True)
def _reset_backend():
    reset_store()
    yield
    reset_store()


@pytest.fixture
async def backend_client():
    transport = httpx.ASGITransport(app=booking_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://booking.test") as client:
        yield BackendClient("http://booking.test", client=client)


@pytest.fixture
def rag() -> KnowledgeRetriever:
    retriever = KnowledgeRetriever(use_chroma=False)
    retriever.ingest()
    return retriever


@pytest.fixture
async def engine(backend_client, rag, today):
    return DialogEngine(
        backend_client,
        rag,
        extractor=HeuristicExtractor(today=today),
        multi_branch=True,
    )
