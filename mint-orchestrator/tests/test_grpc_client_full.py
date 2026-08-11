import pytest
import grpc
from unittest.mock import AsyncMock, MagicMock, patch
from tollgate_mint_orchestrator.grpc_client import MintGrpcClient
from tollgate_mint_orchestrator import grpc_client as grpc_client_mod


class TestMintGrpcClientInit:
    def test_init(self):
        client = MintGrpcClient("localhost", 50051)
        assert client.host == "localhost"
        assert client.port == 50051
        assert client.channel is None
        assert client.stub is None


class TestMintGrpcClientConnect:
    @pytest.mark.asyncio
    async def test_connect_creates_channel(self):
        client = MintGrpcClient("localhost", 50051)
        mock_channel = AsyncMock()
        with patch("tollgate_mint_orchestrator.grpc_client.grpc.aio.insecure_channel", return_value=mock_channel):
            await client.connect()
        assert client.channel is mock_channel

    @pytest.mark.asyncio
    async def test_connect_creates_stub_when_stubs_available(self):
        client = MintGrpcClient("localhost", 50051)
        mock_channel = AsyncMock()
        mock_stub = MagicMock()

        if not hasattr(grpc_client_mod, "cdk_mint_rpc_pb2_grpc"):
            grpc_client_mod.cdk_mint_rpc_pb2_grpc = MagicMock()

        with patch("tollgate_mint_orchestrator.grpc_client.grpc.aio.insecure_channel", return_value=mock_channel):
            with patch.object(grpc_client_mod, "HAS_GRPC_STUBS", True):
                grpc_client_mod.cdk_mint_rpc_pb2_grpc.CdkMintStub.return_value = mock_stub
                await client.connect()
        assert client.stub is mock_stub

    @pytest.mark.asyncio
    async def test_connect_skips_stub_when_stubs_unavailable(self):
        client = MintGrpcClient("localhost", 50051)
        mock_channel = AsyncMock()

        with patch("tollgate_mint_orchestrator.grpc_client.grpc.aio.insecure_channel", return_value=mock_channel):
            with patch.object(grpc_client_mod, "HAS_GRPC_STUBS", False):
                await client.connect()
        assert client.stub is None


class TestMintGrpcClientClose:
    @pytest.mark.asyncio
    async def test_close_channel(self):
        client = MintGrpcClient("localhost", 50051)
        mock_channel = AsyncMock()
        client.channel = mock_channel
        client.stub = MagicMock()
        await client.close()
        mock_channel.close.assert_called_once()
        assert client.channel is None
        assert client.stub is None

    @pytest.mark.asyncio
    async def test_close_no_channel(self):
        client = MintGrpcClient("localhost", 50051)
        await client.close()
        assert client.channel is None


class TestUpdateNut04Quote:
    @pytest.mark.asyncio
    async def test_without_stub(self):
        client = MintGrpcClient("localhost", 50051)
        result = await client.update_nut04_quote("q1", "PAID")
        assert result is False

    @pytest.mark.asyncio
    async def test_success(self):
        client = MintGrpcClient("localhost", 50051)
        mock_stub = AsyncMock()
        mock_stub.UpdateNut04Quote = AsyncMock(return_value=MagicMock())
        client.stub = mock_stub

        original = grpc_client_mod.HAS_GRPC_STUBS
        grpc_client_mod.HAS_GRPC_STUBS = True

        with patch.object(grpc_client_mod, "cdk_mint_rpc_pb2") as mock_pb2:
            mock_pb2.UpdateNut04QuoteRequest.return_value = MagicMock()
            result = await client.update_nut04_quote("q1", "PAID")

        assert result is True
        mock_stub.UpdateNut04Quote.assert_called_once()
        grpc_client_mod.HAS_GRPC_STUBS = original

    @pytest.mark.asyncio
    async def test_grpc_error(self):
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

        original = grpc_client_mod.HAS_GRPC_STUBS
        grpc_client_mod.HAS_GRPC_STUBS = True

        with patch.object(grpc_client_mod, "cdk_mint_rpc_pb2") as mock_pb2:
            mock_pb2.UpdateNut04QuoteRequest.return_value = MagicMock()
            result = await client.update_nut04_quote("q1", "PAID")

        assert result is False
        grpc_client_mod.HAS_GRPC_STUBS = original


class TestGetInfo:
    @pytest.mark.asyncio
    async def test_without_stub(self):
        client = MintGrpcClient("localhost", 50051)
        result = await client.get_info()
        assert result is None

    @pytest.mark.asyncio
    async def test_success(self):
        client = MintGrpcClient("localhost", 50051)
        mock_response = MagicMock()
        mock_response.name = "test-mint"
        mock_response.version = "0.16.0"
        mock_response.description = "A test mint"
        mock_response.total_issued = 1000
        mock_response.total_redeemed = 500

        mock_stub = AsyncMock()
        mock_stub.GetInfo = AsyncMock(return_value=mock_response)
        client.stub = mock_stub

        original = grpc_client_mod.HAS_GRPC_STUBS
        grpc_client_mod.HAS_GRPC_STUBS = True

        with patch.object(grpc_client_mod, "cdk_mint_rpc_pb2") as mock_pb2:
            mock_pb2.GetInfoRequest.return_value = MagicMock()
            result = await client.get_info()

        assert result is not None
        assert result["name"] == "test-mint"
        assert result["version"] == "0.16.0"
        assert result["total_issued"] == 1000
        assert result["total_redeemed"] == 500
        grpc_client_mod.HAS_GRPC_STUBS = original

    @pytest.mark.asyncio
    async def test_grpc_error(self):
        client = MintGrpcClient("localhost", 50051)
        mock_stub = AsyncMock()
        mock_stub.GetInfo = AsyncMock(
            side_effect=grpc.aio.AioRpcError(
                grpc.StatusCode.UNAVAILABLE,
                MagicMock(initial_metadata=(), trailing_metadata=()),
                "unavailable",
            )
        )
        client.stub = mock_stub

        original = grpc_client_mod.HAS_GRPC_STUBS
        grpc_client_mod.HAS_GRPC_STUBS = True

        with patch.object(grpc_client_mod, "cdk_mint_rpc_pb2") as mock_pb2:
            mock_pb2.GetInfoRequest.return_value = MagicMock()
            result = await client.get_info()

        assert result is None
        grpc_client_mod.HAS_GRPC_STUBS = original