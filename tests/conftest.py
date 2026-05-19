import sys, os, pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["ELI_TEST_MODE"] = "1"
os.environ["ELI_FORCE_CPU"] = "1"

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

@pytest.fixture(autouse=True, scope="session")
def mock_heavy_imports():
    with patch.dict(sys.modules, {
        "llama_cpp": MagicMock(), "llama_cpp.llama_cpp": MagicMock(),
        "PySide6": MagicMock(), "PySide6.QtWidgets": MagicMock(),
        "PySide6.QtCore": MagicMock(), "PySide6.QtGui": MagicMock(),
        "faster_whisper": MagicMock(), "sounddevice": MagicMock(),
        "soundfile": MagicMock(), "piper": MagicMock(), "onnxruntime": MagicMock(),
        "faiss": MagicMock(), "torch": MagicMock(), "diffusers": MagicMock(),
        "transformers": MagicMock(), "pydantic": MagicMock(),
    }):
        yield

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_user.sqlite3"
    yield db_path
    if db_path.exists():
        db_path.unlink()

@pytest.fixture
def memory_instance(temp_db):
    from eli.memory import Memory
    return Memory(db_path=temp_db)

@pytest.fixture
def mock_gguf():
    with patch("eli.cognition.gguf_inference") as mock:
        mock.load_model.return_value = MagicMock()
        mock.chat_completion.return_value = {"content": "Mocked GGUF response"}
        mock.generate.return_value = "Mocked generation"
        yield mock

@pytest.fixture
def mock_executor():
    with patch("eli.execution.executor_enhanced.execute") as mock:
        mock.return_value = {"ok": True, "content": "mocked", "response": "mocked"}
        yield mock

@pytest.fixture
def engine_with_mocks(mock_gguf, mock_executor):
    from eli.kernel.engine import CognitiveEngine
    return CognitiveEngine(auto_init_gguf=False)

# FIX: Force persistence gate to allow all memory writes in tests
@pytest.fixture(autouse=True)
def allow_all_persistence():
    with patch("eli.runtime.persistence_gate.should_store_memory_text", return_value=True), \
         patch("eli.runtime.persistence_gate.should_store_conversation_turn", return_value=True):
        yield

# Force persistence gate to allow all memory writes during tests
@pytest.fixture(autouse=True, scope="function")
def force_persistence_gate():
    with patch("eli.memory.memory._eli_should_store_memory_text", None), \
         patch("eli.memory.memory._eli_should_store_conversation_turn", None):
        yield
