"""Test GUI compilation and imports"""
import pytest
from pathlib import Path
from pathlib import Path
import eli as _eli_pkg
_ELI_DIR = Path(_eli_pkg.__file__).resolve().parent  # /home/jay/Desktop/eli/src/eli


def test_gui_import():
    """Test that GUI module can be imported (if dependencies available)"""
    try:
        import eli.gui.eli_pro_audio_gui_MKI
        assert True, "GUI imported successfully"
    except ModuleNotFoundError as e:
        if 'PySide6' in str(e) or 'PyQt' in str(e):
            pytest.skip("GUI dependencies (PySide6/PyQt) not installed in test environment")
        else:
            # Re-raise if it's a different import error
            raise


def test_gui_no_syntax_errors():
    """Test that GUI file has no syntax errors"""
    import ast
    
    # Find the GUI file
    test_dir = Path(__file__).parent
    gui_path = _ELI_DIR / 'gui' / 'eli_pro_audio_gui_MKI.py'
    
    assert gui_path.exists(), f"GUI file not found at {gui_path}"
    
    # Parse the file to check for syntax errors
    with open(gui_path) as f:
        source = f.read()
        ast.parse(source)
    
    assert True, "GUI file has valid Python syntax"