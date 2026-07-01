"""Tests for external transaction tools (alternative billing)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import play_store_mcp.server as server
from play_store_mcp.client import PlayStoreClient, PlayStoreClientError
from play_store_mcp.models import ExternalTransaction

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_external_transaction_defaults():
    tx = ExternalTransaction(
        package_name="com.example.app",
        external_transaction_id="tx123",
    )
    assert tx.transaction_state is None
    assert tx.create_time is None
    assert tx.current_pre_tax_amount is None
    assert tx.original_pre_tax_amount is None
    assert tx.test_purchase is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_http_error(reason: str = "boom") -> HttpError:
    resp = MagicMock()
    resp.status = 400
    resp.reason = reason
    err = HttpError(resp, b"{}")
    err.reason = reason
    return err


def _client(service: MagicMock) -> PlayStoreClient:
    client = PlayStoreClient(credentials_json={"type": "service_account"})
    client._service = service
    return client


def _ext(service: MagicMock) -> MagicMock:
    return service.externaltransactions.return_value


_NAME = "applications/com.example.app/externalTransactions/tx123"
_PARENT = "applications/com.example.app"


# ---------------------------------------------------------------------------
# Client: get_external_transaction
# ---------------------------------------------------------------------------


def test_get_external_transaction_success():
    service = MagicMock()
    _ext(service).getexternaltransaction.return_value.execute.return_value = {
        "externalTransactionId": _NAME,
        "transactionState": "TRANSACTION_COMPLETED",
        "createTime": "2026-01-01T00:00:00Z",
        "currentPreTaxAmount": {"currencyCode": "USD", "units": "1"},
        "originalPreTaxAmount": {"currencyCode": "USD", "units": "1"},
        "testPurchase": {},
    }
    client = _client(service)

    result = client.get_external_transaction("com.example.app", "tx123")

    assert result.external_transaction_id == "tx123"
    assert result.transaction_state == "TRANSACTION_COMPLETED"
    assert result.create_time == "2026-01-01T00:00:00Z"
    assert result.current_pre_tax_amount == {"currencyCode": "USD", "units": "1"}
    assert result.original_pre_tax_amount == {"currencyCode": "USD", "units": "1"}
    assert result.test_purchase is True
    _ext(service).getexternaltransaction.assert_called_once_with(name=_NAME)


def test_get_external_transaction_minimal():
    service = MagicMock()
    _ext(service).getexternaltransaction.return_value.execute.return_value = {}
    client = _client(service)

    result = client.get_external_transaction("com.example.app", "tx123")

    assert result.external_transaction_id == "tx123"
    assert result.transaction_state is None
    assert result.test_purchase is False


def test_get_external_transaction_http_error():
    service = MagicMock()
    _ext(service).getexternaltransaction.return_value.execute.side_effect = _make_http_error("nope")
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to get external transaction"):
        client.get_external_transaction("com.example.app", "tx123")


# ---------------------------------------------------------------------------
# Client: create_external_transaction
# ---------------------------------------------------------------------------


def test_create_external_transaction_success():
    service = MagicMock()
    _ext(service).createexternaltransaction.return_value.execute.return_value = {
        "externalTransactionId": _NAME,
        "transactionState": "TRANSACTION_COMPLETED",
    }
    client = _client(service)
    body = {"originalPreTaxAmount": {"currencyCode": "USD", "units": "1"}}

    result = client.create_external_transaction("com.example.app", "tx123", body)

    assert result.external_transaction_id == "tx123"
    assert result.transaction_state == "TRANSACTION_COMPLETED"
    _ext(service).createexternaltransaction.assert_called_once_with(
        parent=_PARENT, externalTransactionId="tx123", body=body
    )


def test_create_external_transaction_http_error():
    service = MagicMock()
    _ext(service).createexternaltransaction.return_value.execute.side_effect = _make_http_error(
        "bad"
    )
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to create external transaction"):
        client.create_external_transaction("com.example.app", "tx123", {})


# ---------------------------------------------------------------------------
# Client: refund_external_transaction
# ---------------------------------------------------------------------------


def test_refund_external_transaction_success():
    service = MagicMock()
    _ext(service).refundexternaltransaction.return_value.execute.return_value = {
        "externalTransactionId": _NAME,
        "transactionState": "TRANSACTION_CANCELED",
    }
    client = _client(service)
    body = {"fullRefund": {}}

    result = client.refund_external_transaction("com.example.app", "tx123", body)

    assert result.external_transaction_id == "tx123"
    assert result.transaction_state == "TRANSACTION_CANCELED"
    _ext(service).refundexternaltransaction.assert_called_once_with(name=_NAME, body=body)


def test_refund_external_transaction_http_error():
    service = MagicMock()
    _ext(service).refundexternaltransaction.return_value.execute.side_effect = _make_http_error(
        "bad"
    )
    client = _client(service)

    with pytest.raises(PlayStoreClientError, match="Failed to refund external transaction"):
        client.refund_external_transaction("com.example.app", "tx123", {})


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_tool_get_external_transaction(monkeypatch):
    mc = MagicMock()
    mc.get_external_transaction.return_value = ExternalTransaction(
        package_name="com.example.app",
        external_transaction_id="tx123",
        transaction_state="TRANSACTION_COMPLETED",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)

    result = server.get_external_transaction("com.example.app", "tx123")

    assert result["external_transaction_id"] == "tx123"
    assert result["transaction_state"] == "TRANSACTION_COMPLETED"
    mc.get_external_transaction.assert_called_once_with(
        package_name="com.example.app", external_transaction_id="tx123"
    )


def test_tool_create_external_transaction(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.create_external_transaction.return_value = ExternalTransaction(
        package_name="com.example.app", external_transaction_id="tx123"
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)
    body = {"originalPreTaxAmount": {"currencyCode": "USD", "units": "1"}}

    result = server.create_external_transaction("com.example.app", "tx123", body)

    assert result["external_transaction_id"] == "tx123"
    mc.create_external_transaction.assert_called_once_with(
        package_name="com.example.app", external_transaction_id="tx123", transaction=body
    )


def test_tool_refund_external_transaction(monkeypatch):
    monkeypatch.setattr(server, "READ_ONLY", False)
    mc = MagicMock()
    mc.refund_external_transaction.return_value = ExternalTransaction(
        package_name="com.example.app",
        external_transaction_id="tx123",
        transaction_state="TRANSACTION_CANCELED",
    )
    monkeypatch.setattr(server, "get_client_from_context", lambda: mc)
    body = {"fullRefund": {}}

    result = server.refund_external_transaction("com.example.app", "tx123", body)

    assert result["transaction_state"] == "TRANSACTION_CANCELED"
    mc.refund_external_transaction.assert_called_once_with(
        package_name="com.example.app", external_transaction_id="tx123", refund=body
    )
