import pytest
from unittest.mock import AsyncMock, MagicMock
from tollgate_mint_orchestrator.grpc_client import MintGrpcClient


class TestMintGrpcClient:
    def test_init(self):
        client = MintGrpcClient("localhost", 50051)
        assert client.host == "localhost"
        assert client.port == 50051
        assert client.channel is None

    @pytest.mark.asyncio
    async def test_update_without_connection(self):
        client = MintGrpcClient("localhost", 50051)
        result = await client.update_nut04_quote("q1", "PAID")
        assert result is False

    @pytest.mark.asyncio
    async def test_info_without_connection(self):
        client = MintGrpcClient("localhost", 50051)
        result = await client.get_info()
        assert result is None


class TestMintGrpcClientWithMock:
    @pytest.mark.asyncio
    async def test_update_nut04_quote_success(self):
        client = MintGrpcClient("localhost", 50051)
        mock_stub = AsyncMock()
        mock_stub.UpdateNut04Quote = AsyncMock(return_value=MagicMock())
        client.stub = mock_stub

        from tollgate_mint_orchestrator import grpc_client
        original = grpc_client.HAS_GRPC_STUBS
        grpc_client.HAS_GRPC_STUBS = True

        result = await client.update_nut04_quote("q1", "PAID")
        assert result is True
        mock_stub.UpdateNut04Quote.assert_called_once()

        grpc_client.HAS_GRPC_STUBS = original

    @pytest.mark.asyncio
    async def test_update_nut04_quote_grpc_error(self):
        import grpc
        client = MintGrpcClient("localhost", 50051)
        mock_stub = AsyncMock()
        mock_stub.UpdateNut04Quote = AsyncMock(
            side_effect=grpc.aio.AioRpcError(
                grpc.StatusCode.NOT_FOUND,
                MagicMock(initial_metadata=(), trailing_metadata=()),
                "not found",
            )
        )
        client.stub = mock_stub

        from tollgate_mint_orchestrator import grpc_client
        original = grpc_client.HAS_GRPC_STUBS
        grpc_client.HAS_GRPC_STUBS = True

        result = await client.update_nut04_quote("q1", "PAID")
        assert result is False

        grpc_client.HAS_GRPC_STUBS = original
