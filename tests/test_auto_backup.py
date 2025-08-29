import os
import json
import tempfile
import shutil
import asyncio
import types
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

from talemate import auto_backup
from talemate.config import Config
from talemate.config.schema import General, Game


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_save_dir():
    """Create a temporary directory for save files."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_scene(temp_save_dir):
    """Create a mock scene object with all necessary attributes."""
    scene = types.SimpleNamespace()
    scene.name = "Test Scene"
    scene.filename = "test_scene.json"
    scene.save_dir = temp_save_dir
    scene.serialize = {
        "name": "Test Scene",
        "description": "A test scene",
        "characters": [],
        "history": []
    }
    return scene


@pytest.fixture
def mock_config():
    """Create a mock config with auto backup settings."""
    config = Config()
    config.game = Game()
    config.game.general = General()
    config.game.general.auto_backup = True
    config.game.general.auto_backup_max_backups = 3
    return config


@pytest.fixture
def disabled_auto_backup_config():
    """Create a mock config with auto backup disabled."""
    config = Config()
    config.game = Game() 
    config.game.general = General()
    config.game.general.auto_backup = False
    config.game.general.auto_backup_max_backups = 3
    return config


# ---------------------------------------------------------------------------
# Tests for auto_backup function
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_backup_disabled(mock_scene, disabled_auto_backup_config):
    """Test that auto backup does nothing when disabled."""
    with patch('talemate.auto_backup.get_config', return_value=disabled_auto_backup_config):
        await auto_backup.auto_backup(mock_scene)
        
        # No backup directory should be created
        backups_dir = os.path.join(mock_scene.save_dir, "backups")
        assert not os.path.exists(backups_dir)


@pytest.mark.asyncio
async def test_auto_backup_no_filename(mock_config):
    """Test that auto backup skips scenes with no filename."""
    scene = types.SimpleNamespace()
    scene.filename = None
    scene.name = "Test Scene"
    
    with patch('talemate.auto_backup.get_config', return_value=mock_config):
        await auto_backup.auto_backup(scene)
        
        # No backup should be created since scene has no filename


@pytest.mark.asyncio
async def test_auto_backup_no_name(mock_config, temp_save_dir):
    """Test that auto backup skips scenes with no name."""
    scene = types.SimpleNamespace()
    scene.filename = "test.json"
    scene.name = None
    scene.save_dir = temp_save_dir
    
    with patch('talemate.auto_backup.get_config', return_value=mock_config):
        await auto_backup.auto_backup(scene)
        
        # No backup directory should be created
        backups_dir = os.path.join(temp_save_dir, "backups")
        assert not os.path.exists(backups_dir)


@pytest.mark.asyncio
async def test_auto_backup_creates_backup(mock_scene, mock_config):
    """Test that auto backup creates a backup file."""
    with patch('talemate.auto_backup.get_config', return_value=mock_config):
        await auto_backup.auto_backup(mock_scene)
        
        # Check that backup directory was created
        backups_dir = os.path.join(mock_scene.save_dir, "backups")
        assert os.path.exists(backups_dir)
        
        # Check that a backup file was created
        backup_files = [f for f in os.listdir(backups_dir) if f.startswith("test_scene_backup_")]
        assert len(backup_files) == 1
        
        # Check backup file content
        backup_path = os.path.join(backups_dir, backup_files[0])
        with open(backup_path, 'r') as f:
            backup_data = json.load(f)
        
        assert backup_data["name"] == "Test Scene"
        assert backup_data["description"] == "A test scene"


@pytest.mark.asyncio
async def test_auto_backup_filename_format(mock_scene, mock_config):
    """Test that backup filenames follow the expected format."""
    with patch('talemate.auto_backup.get_config', return_value=mock_config):
        # Mock datetime.now() to return a consistent timestamp
        mock_now = MagicMock()
        mock_now.strftime.return_value = "20250829_143022"
        
        with patch('talemate.auto_backup.datetime.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_now
            
            await auto_backup.auto_backup(mock_scene)
            
            backups_dir = os.path.join(mock_scene.save_dir, "backups")
            backup_files = os.listdir(backups_dir)
            
            assert len(backup_files) == 1
            assert backup_files[0] == "test_scene_backup_20250829_143022.json"


# ---------------------------------------------------------------------------
# Tests for cleanup functionality
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_old_backups(mock_scene, mock_config):
    """Test that old backups are cleaned up when exceeding max_backups."""
    backups_dir = os.path.join(mock_scene.save_dir, "backups")
    os.makedirs(backups_dir)
    
    # Create 5 backup files (more than max_backups = 3)
    for i in range(5):
        backup_name = f"test_scene_backup_2025082{i}_143022.json"
        backup_path = os.path.join(backups_dir, backup_name)
        with open(backup_path, 'w') as f:
            json.dump({"backup": i}, f)
    
    with patch('talemate.auto_backup.get_config', return_value=mock_config):
        await auto_backup.auto_backup(mock_scene)
        
        # Should have max_backups + 1 (newly created) = 4 files initially
        # But cleanup should reduce it to max_backups = 3
        backup_files = [f for f in os.listdir(backups_dir) if f.startswith("test_scene_backup_")]
        assert len(backup_files) <= 3


@pytest.mark.asyncio 
async def test_cleanup_zero_max_backups(mock_scene):
    """Test that cleanup handles zero max_backups correctly."""
    config = Config()
    config.game = Game()
    config.game.general = General()
    config.game.general.auto_backup = True
    config.game.general.auto_backup_max_backups = 0
    
    backups_dir = os.path.join(mock_scene.save_dir, "backups")
    os.makedirs(backups_dir)
    
    # Create some backup files
    for i in range(3):
        backup_name = f"test_scene_backup_2025082{i}_143022.json"
        backup_path = os.path.join(backups_dir, backup_name)
        with open(backup_path, 'w') as f:
            json.dump({"backup": i}, f)
    
    with patch('talemate.auto_backup.get_config', return_value=config):
        await auto_backup.auto_backup(mock_scene)
        
        # All old backups should remain since max_backups=0 means no cleanup
        backup_files = [f for f in os.listdir(backups_dir) if f.startswith("test_scene_backup_")]
        assert len(backup_files) == 4  # 3 original + 1 new


@pytest.mark.asyncio
async def test_cleanup_different_scenes(mock_config, temp_save_dir):
    """Test that cleanup only affects backups for the same scene."""
    backups_dir = os.path.join(temp_save_dir, "backups")
    os.makedirs(backups_dir)
    
    # Create backups for different scenes
    for scene_name in ["scene1", "scene2", "test_scene"]:
        for i in range(2):
            backup_name = f"{scene_name}_backup_2025082{i}_143022.json"
            backup_path = os.path.join(backups_dir, backup_name)
            with open(backup_path, 'w') as f:
                json.dump({"scene": scene_name, "backup": i}, f)
    
    # Create scene for test_scene
    scene = types.SimpleNamespace()
    scene.name = "Test Scene"
    scene.filename = "test_scene.json"
    scene.save_dir = temp_save_dir
    scene.serialize = {"name": "Test Scene"}
    
    with patch('talemate.auto_backup.get_config', return_value=mock_config):
        await auto_backup.auto_backup(scene)
        
        # Check that other scene backups weren't affected
        scene1_backups = [f for f in os.listdir(backups_dir) if f.startswith("scene1_backup_")]
        scene2_backups = [f for f in os.listdir(backups_dir) if f.startswith("scene2_backup_")]
        
        assert len(scene1_backups) == 2
        assert len(scene2_backups) == 2


# ---------------------------------------------------------------------------
# Tests for get_backup_files function
# ---------------------------------------------------------------------------


def test_get_backup_files_no_scene_filename(temp_save_dir):
    """Test get_backup_files returns empty list when scene has no filename."""
    scene = types.SimpleNamespace()
    scene.filename = None
    scene.name = "Test Scene"
    scene.save_dir = temp_save_dir
    
    result = auto_backup.get_backup_files(scene)
    assert result == []


def test_get_backup_files_no_backups_dir(mock_scene):
    """Test get_backup_files returns empty list when backups directory doesn't exist."""
    result = auto_backup.get_backup_files(mock_scene)
    assert result == []


def test_get_backup_files_empty_backups_dir(mock_scene):
    """Test get_backup_files returns empty list when backups directory is empty."""
    backups_dir = os.path.join(mock_scene.save_dir, "backups")
    os.makedirs(backups_dir)
    
    result = auto_backup.get_backup_files(mock_scene)
    assert result == []


def test_get_backup_files_with_backups(mock_scene):
    """Test get_backup_files returns correct backup file information."""
    backups_dir = os.path.join(mock_scene.save_dir, "backups")
    os.makedirs(backups_dir)
    
    # Create backup files
    backup_names = [
        "test_scene_backup_20250829_143022.json",
        "test_scene_backup_20250829_143045.json"
    ]
    
    for name in backup_names:
        backup_path = os.path.join(backups_dir, name)
        with open(backup_path, 'w') as f:
            json.dump({"test": "data"}, f)
    
    result = auto_backup.get_backup_files(mock_scene)
    
    assert len(result) == 2
    
    # Check that results are sorted by timestamp (newest first)
    timestamps = [backup["timestamp"] for backup in result]
    assert timestamps == sorted(timestamps, reverse=True)
    
    # Check that each backup has required fields
    for backup in result:
        assert "name" in backup
        assert "path" in backup
        assert "timestamp" in backup
        assert "size" in backup
        assert backup["name"].startswith("test_scene_backup_")


def test_get_backup_files_filters_other_scenes(mock_scene):
    """Test get_backup_files only returns backups for the correct scene."""
    backups_dir = os.path.join(mock_scene.save_dir, "backups")
    os.makedirs(backups_dir)
    
    # Create backup files for different scenes
    files = [
        "test_scene_backup_20250829_143022.json",  # Should be included
        "other_scene_backup_20250829_143022.json",  # Should be excluded
        "test_scene_backup_20250829_143045.json",  # Should be included
        "random_file.json"  # Should be excluded
    ]
    
    for name in files:
        backup_path = os.path.join(backups_dir, name)
        with open(backup_path, 'w') as f:
            json.dump({"test": "data"}, f)
    
    result = auto_backup.get_backup_files(mock_scene)
    
    # Should only return the 2 backups for test_scene
    assert len(result) == 2
    for backup in result:
        assert backup["name"].startswith("test_scene_backup_")


# ---------------------------------------------------------------------------
# Tests for error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_backup_file_write_error(mock_scene, mock_config):
    """Test auto backup handles file write errors gracefully."""
    with patch('talemate.auto_backup.get_config', return_value=mock_config):
        with patch('builtins.open', side_effect=PermissionError("Permission denied")):
            # Should not raise an exception, just log the error
            await auto_backup.auto_backup(mock_scene)
            
            # Verify no backup was created due to the error
            backups_dir = os.path.join(mock_scene.save_dir, "backups")
            if os.path.exists(backups_dir):
                backup_files = os.listdir(backups_dir)
                assert len(backup_files) == 0


@pytest.mark.asyncio
async def test_cleanup_handles_removal_errors(mock_scene, mock_config):
    """Test that cleanup handles file removal errors gracefully."""
    backups_dir = os.path.join(mock_scene.save_dir, "backups")
    os.makedirs(backups_dir)
    
    # Create more backup files than max_backups
    for i in range(5):
        backup_name = f"test_scene_backup_2025082{i}_143022.json"
        backup_path = os.path.join(backups_dir, backup_name)
        with open(backup_path, 'w') as f:
            json.dump({"backup": i}, f)
    
    with patch('talemate.auto_backup.get_config', return_value=mock_config):
        with patch('os.remove', side_effect=OSError("Cannot remove file")):
            # Should not raise an exception, just log the error
            try:
                await auto_backup.auto_backup(mock_scene)
            except OSError:
                pytest.fail("auto_backup cleanup should handle file removal errors gracefully")


def test_get_backup_files_handles_listdir_error(mock_scene):
    """Test get_backup_files handles directory listing errors gracefully."""
    backups_dir = os.path.join(mock_scene.save_dir, "backups")
    os.makedirs(backups_dir)
    
    with patch('os.listdir', side_effect=OSError("Cannot list directory")):
        result = auto_backup.get_backup_files(mock_scene)
        assert result == []


# ---------------------------------------------------------------------------
# Integration-style tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_backup_cycles(mock_scene, mock_config):
    """Test multiple backup cycles work correctly."""
    with patch('talemate.auto_backup.get_config', return_value=mock_config):
        # Create multiple backups
        for i in range(5):
            mock_scene.serialize = {"backup_number": i, "name": "Test Scene"}
            await auto_backup.auto_backup(mock_scene)
            
        backups_dir = os.path.join(mock_scene.save_dir, "backups")
        backup_files = [f for f in os.listdir(backups_dir) if f.startswith("test_scene_backup_")]
        
        # Should respect max_backups = 3
        assert len(backup_files) <= 3
        
        # Verify the content of remaining backups
        for backup_file in backup_files:
            backup_path = os.path.join(backups_dir, backup_file)
            with open(backup_path, 'r') as f:
                backup_data = json.load(f)
            assert "backup_number" in backup_data
            assert backup_data["name"] == "Test Scene"