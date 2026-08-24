from apps.voice_agent.extractor import HeuristicExtractor, fold_vi
from apps.voice_agent.rag import KnowledgeRetriever
from shared.config import REPO_ROOT


def test_ingest_markdown_files():
    rag = KnowledgeRetriever(knowledge_dir=REPO_ROOT / "knowledge", use_chroma=False)
    chunks = rag.ingest()
    sources = {chunk.source for chunk in chunks}
    assert "gio_mo_cua.md" in sources
    assert "gui_xe.md" in sources
    assert "chinh_sach_huy.md" in sources


def test_retrieve_opening_hours():
    rag = KnowledgeRetriever(use_chroma=False)
    rag.ingest()
    hits = rag.retrieve("Nha hang mo cua luc may gio?")
    assert hits
    blob = " ".join(hit.text for hit in hits)
    assert "11:00" in blob
    assert "22:00" in blob


def test_retrieve_parking_not_availability():
    rag = KnowledgeRetriever(use_chroma=False)
    rag.ingest()
    hits = rag.retrieve("gui xe o to bao nhieu tien")
    assert hits
    assert any("30.000" in hit.text or "valet" in fold_vi(hit.text) for hit in hits)


def test_chroma_flag_falls_back_to_lexical(tmp_path):
    rag = KnowledgeRetriever(use_chroma=True, chroma_path=str(tmp_path / "chroma"), openai_api_key="")
    rag.ingest()
    hits = rag.retrieve("chinh sach huy ban")
    assert hits
    assert any("3 gio" in fold_vi(hit.text) or "3 giờ" in hit.text for hit in hits)
