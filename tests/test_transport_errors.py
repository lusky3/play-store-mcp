"""Transport errors (dead keep-alive sockets) are retried and drop the connection pool.

httplib2 keeps a pooled connection open between calls. When Google closes it
while idle, the next request fails with BrokenPipeError or an SSL EOF, and
httplib2 re-raises a send-side failure without discarding the dead connection,
so every later call on the shared transport would fail the same way.
"""

from __future__ import annotations

import ssl
from typing import Any
from unittest.mock import MagicMock

import google_auth_httplib2
import httplib2
import pytest
from googleapiclient.http import HttpRequest

import play_store_mcp.client as client_module
from play_store_mcp.client import MAX_RETRIES, PlayStoreClient, retry_with_backoff


def _get_request(service: MagicMock) -> MagicMock:
    request = service.orders.return_value.get.return_value
    request.method = "GET"
    return request


_ORDER = {"orderId": "order-1", "state": "PROCESSED", "lineItems": [], "purchaseToken": "tok"}


class TestTransportErrorRetry:
    @pytest.mark.parametrize(
        "error",
        [
            BrokenPipeError(32, "Broken pipe"),
            ConnectionResetError(104, "Connection reset by peer"),
            ssl.SSLEOFError(8, "UNEXPECTED_EOF_WHILE_READING"),
        ],
    )
    def test_idempotent_request_retries_and_drops_pool(
        self, client: PlayStoreClient, _mock_service: MagicMock, error: Exception
    ) -> None:
        request = _get_request(_mock_service)
        request.execute.side_effect = [error, _ORDER]

        order = client.get_order("com.example.app", "order-1")

        assert order.order_id == "order-1"
        assert request.execute.call_count == 2
        request.http.close.assert_called_once()

    def test_non_idempotent_request_not_retried_but_pool_dropped(
        self, client: PlayStoreClient, _mock_service: MagicMock
    ) -> None:
        """A POST may already have been applied, so it fails; the next call still reconnects."""
        ack = _mock_service.purchases.return_value.products.return_value.acknowledge.return_value
        ack.method = "POST"
        ack.execute.side_effect = [BrokenPipeError(32, "Broken pipe"), {}]

        result = client.acknowledge_product_purchase("com.example.app", "sku-1", "tok-1")

        assert result.success is False
        assert ack.execute.call_count == 1
        ack.http.close.assert_called_once()

    def test_create_edit_retries_despite_being_a_post(
        self, client: PlayStoreClient, _mock_service: MagicMock
    ) -> None:
        """edits.insert opts in: a duplicate uncommitted edit is harmless."""
        insert = _mock_service.edits.return_value.insert.return_value
        insert.method = "POST"
        insert.execute.side_effect = [BrokenPipeError(32, "Broken pipe"), {"id": "edit-1"}]

        assert client._create_edit("com.example.app") == "edit-1"
        assert insert.execute.call_count == 2

    def test_persistent_transport_error_raises_after_max_retries(
        self, client: PlayStoreClient, _mock_service: MagicMock
    ) -> None:
        request = _get_request(_mock_service)
        request.execute.side_effect = ConnectionResetError(104, "Connection reset by peer")

        with pytest.raises(ConnectionResetError):
            client.get_order("com.example.app", "order-1")

        assert request.execute.call_count == MAX_RETRIES
        assert request.http.close.call_count == MAX_RETRIES

    def test_other_oserrors_are_not_retried(self) -> None:
        """Only connection-level failures retry; e.g. a missing upload file must not."""
        calls = 0

        @retry_with_backoff
        def missing_file() -> None:
            nonlocal calls
            calls += 1
            raise FileNotFoundError("app.aab")

        with pytest.raises(FileNotFoundError):
            missing_file()

        assert calls == 1


class TestDownloadTransportError:
    def test_download_chunk_transport_error_drops_pool(
        self,
        client: PlayStoreClient,
        _mock_service: MagicMock,
        tmp_path: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        request = _mock_service.generatedapks.return_value.download.return_value

        class _FailingDownloader:
            def __init__(self, fh: Any, req: Any) -> None:
                pass

            def next_chunk(self) -> tuple[Any, bool]:
                raise BrokenPipeError(32, "Broken pipe")

        monkeypatch.setattr(client_module, "MediaIoBaseDownload", _FailingDownloader)
        client._download_dir = str(tmp_path)

        with pytest.raises(BrokenPipeError):
            client._download_to_file(request, str(tmp_path / "app.apk"))

        request.http.close.assert_called_once()
        assert not list(tmp_path.glob("*.part"))


class TestDropPooledConnectionsOnRealTransport:
    def test_closes_and_clears_the_httplib2_pool(self, client: PlayStoreClient) -> None:
        """Against real googleapiclient/httplib2 objects, not just mocks."""
        authed = google_auth_httplib2.AuthorizedHttp(MagicMock(), http=httplib2.Http())
        dead_conn = MagicMock()
        authed.http.connections["https:androidpublisher.googleapis.com"] = dead_conn
        request = HttpRequest(authed, lambda _resp, content: content, "https://example.invalid")

        client._drop_pooled_connections(request)

        dead_conn.close.assert_called_once()
        assert authed.http.connections == {}

    def test_request_without_a_closable_transport_is_a_no_op(self, client: PlayStoreClient) -> None:
        client._drop_pooled_connections(object())
