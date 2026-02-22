"""Tests for the credentials HTTP endpoint."""

import json
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


@pytest.fixture
def mock_credentials():
    """Mock service account credentials."""
    return {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "test-key-id",
        "private_key": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----",
        "client_email": "test@test-project.iam.gserviceaccount.com",
        "client_id": "123456789",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    }


@pytest.mark.asyncio
async def test_update_credentials_with_json_object(mock_credentials):
    """Test updating credentials with JSON object."""
    from starlette.requests import Request
    from play_store_mcp.server import update_credentials, mcp
    
    with patch("play_store_mcp.client.PlayStoreClient._get_service") as mock_service:
        mock_service.return_value = MagicMock()
        
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={"credentials": mock_credentials})
        
        mcp._shared_state = {"client": None, "credentials_updated": False}
        
        response = await update_credentials(mock_request)
        
        assert response.status_code == 200
        data = json.loads(response.body)
        assert data["success"] is True
        assert "updated successfully" in data["message"]


@pytest.mark.asyncio
async def test_update_credentials_with_json_string(mock_credentials):
    """Test updating credentials with JSON string."""
    from starlette.requests import Request
    from play_store_mcp.server import update_credentials, mcp
    
    with patch("play_store_mcp.client.PlayStoreClient._get_service") as mock_service:
        mock_service.return_value = MagicMock()
        
        credentials_str = json.dumps(mock_credentials)
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={"credentials": credentials_str})
        
        mcp._shared_state = {"client": None, "credentials_updated": False}
        
        response = await update_credentials(mock_request)
        
        assert response.status_code == 200
        data = json.loads(response.body)
        assert data["success"] is True


@pytest.mark.asyncio
async def test_update_credentials_with_path(tmp_path):
    """Test updating credentials with file path."""
    from starlette.requests import Request
    from play_store_mcp.server import update_credentials, mcp
    
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text(json.dumps({
        "type": "service_account",
        "project_id": "test",
    }))
    
    with patch("play_store_mcp.client.PlayStoreClient._get_service") as mock_service:
        mock_service.return_value = MagicMock()
        
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={"credentials_path": str(creds_file)})
        
        mcp._shared_state = {"client": None, "credentials_updated": False}
        
        response = await update_credentials(mock_request)
        
        assert response.status_code == 200
        data = json.loads(response.body)
        assert data["success"] is True


@pytest.mark.asyncio
async def test_update_credentials_missing_data():
    """Test error when no credentials provided."""
    from starlette.requests import Request
    from play_store_mcp.server import update_credentials, mcp
    
    mock_request = MagicMock(spec=Request)
    mock_request.json = AsyncMock(return_value={})
    
    mcp._shared_state = {"client": None, "credentials_updated": False}
    
    response = await update_credentials(mock_request)
    
    assert response.status_code == 400
    data = json.loads(response.body)
    assert data["success"] is False
    assert "Missing" in data["error"]


@pytest.mark.asyncio
async def test_update_credentials_invalid_json_string():
    """Test error with invalid JSON string."""
    from starlette.requests import Request
    from play_store_mcp.server import update_credentials, mcp
    
    mock_request = MagicMock(spec=Request)
    mock_request.json = AsyncMock(return_value={"credentials": "not valid json"})
    
    mcp._shared_state = {"client": None, "credentials_updated": False}
    
    response = await update_credentials(mock_request)
    
    assert response.status_code == 400
    data = json.loads(response.body)
    assert data["success"] is False
    assert "Invalid JSON" in data["error"]


@pytest.mark.asyncio
async def test_update_credentials_invalid_type():
    """Test error with invalid credentials type."""
    from starlette.requests import Request
    from play_store_mcp.server import update_credentials, mcp
    
    mock_request = MagicMock(spec=Request)
    mock_request.json = AsyncMock(return_value={"credentials": 123})
    
    mcp._shared_state = {"client": None, "credentials_updated": False}
    
    response = await update_credentials(mock_request)
    
    assert response.status_code == 400
    data = json.loads(response.body)
    assert data["success"] is False
    assert "must be a string or object" in data["error"]


@pytest.mark.asyncio
async def test_update_credentials_invalid_credentials(mock_credentials):
    """Test error with invalid credentials that fail validation."""
    from starlette.requests import Request
    from play_store_mcp.server import update_credentials, mcp
    
    with patch("play_store_mcp.client.PlayStoreClient._get_service") as mock_service:
        from play_store_mcp.client import PlayStoreClientError
        mock_service.side_effect = PlayStoreClientError("Invalid credentials")
        
        mock_request = MagicMock(spec=Request)
        mock_request.json = AsyncMock(return_value={"credentials": mock_credentials})
        
        mcp._shared_state = {"client": None, "credentials_updated": False}
        
        response = await update_credentials(mock_request)
        
        assert response.status_code == 401
        data = json.loads(response.body)
        assert data["success"] is False
        assert "Invalid credentials" in data["error"]


@pytest.mark.asyncio
async def test_update_credentials_malformed_request():
    """Test error with malformed JSON request."""
    from starlette.requests import Request
    from play_store_mcp.server import update_credentials, mcp
    
    mock_request = MagicMock(spec=Request)
    mock_request.json = AsyncMock(side_effect=json.JSONDecodeError("test", "test", 0))
    
    mcp._shared_state = {"client": None, "credentials_updated": False}
    
    response = await update_credentials(mock_request)
    
    assert response.status_code == 400
    data = json.loads(response.body)
    assert data["success"] is False
