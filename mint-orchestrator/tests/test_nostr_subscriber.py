import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from tollgate_mint_orchestrator.nostr_subscriber import NostrSubscriber


class TestNostrSubscriberInit:
    def test_init_sets_attributes(self):
        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])
        assert sub.relay_url == "ws://localhost:7777"
        assert sub.filters == [{"kinds": [38010]}]
        assert len(sub.sub_id) == 8
        assert sub._running is False
        assert sub._ws is None
        assert sub._backoff == 1
        assert sub._max_backoff == 60


class TestNostrSubscriberStart:
    @pytest.mark.asyncio
    async def test_connects_and_sends_req(self):
        messages_sent = []

        class FakeWS:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def send(self, msg):
                messages_sent.append(msg)
            def __aiter__(self):
                return self
            async def __anext__(self):
                sub._running = False
                raise StopAsyncIteration

        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])
        on_event = AsyncMock()

        with patch("tollgate_mint_orchestrator.nostr_subscriber.websockets.connect", return_value=FakeWS()):
            await sub.start(on_event)

        assert len(messages_sent) == 1
        msg = json.loads(messages_sent[0])
        assert msg[0] == "REQ"
        assert msg[1] == sub.sub_id

    @pytest.mark.asyncio
    async def test_processes_event_messages(self):
        events_received = []

        class FakeWS:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def send(self, msg):
                pass
            def __aiter__(self):
                return self
            async def __anext__(self):
                if not hasattr(self, '_sent'):
                    self._sent = True
                    return json.dumps(["EVENT", "sub1", {"kind": 38010, "content": "test"}])
                sub._running = False
                raise StopAsyncIteration

        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])

        async def on_event(event):
            events_received.append(event)

        with patch("tollgate_mint_orchestrator.nostr_subscriber.websockets.connect", return_value=FakeWS()):
            await sub.start(on_event)

        assert len(events_received) == 1
        assert events_received[0]["kind"] == 38010

    @pytest.mark.asyncio
    async def test_handles_eose_without_callback(self):
        callbacks = []

        class FakeWS:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def send(self, msg):
                pass
            def __aiter__(self):
                return self
            async def __anext__(self):
                if not hasattr(self, '_sent'):
                    self._sent = True
                    return json.dumps(["EOSE", "sub1"])
                sub._running = False
                raise StopAsyncIteration

        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])

        async def on_event(event):
            callbacks.append(event)

        with patch("tollgate_mint_orchestrator.nostr_subscriber.websockets.connect", return_value=FakeWS()):
            await sub.start(on_event)

        assert len(callbacks) == 0

    @pytest.mark.asyncio
    async def test_handles_notice_without_callback(self):
        callbacks = []

        class FakeWS:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def send(self, msg):
                pass
            def __aiter__(self):
                return self
            async def __anext__(self):
                if not hasattr(self, '_sent'):
                    self._sent = True
                    return json.dumps(["NOTICE", "rate limited"])
                sub._running = False
                raise StopAsyncIteration

        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])

        async def on_event(event):
            callbacks.append(event)

        with patch("tollgate_mint_orchestrator.nostr_subscriber.websockets.connect", return_value=FakeWS()):
            await sub.start(on_event)

        assert len(callbacks) == 0

    @pytest.mark.asyncio
    async def test_ignores_invalid_json(self):
        callbacks = []

        class FakeWS:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def send(self, msg):
                pass
            def __aiter__(self):
                return self
            async def __anext__(self):
                if not hasattr(self, '_sent'):
                    self._sent = True
                    return "not valid json{{{"
                sub._running = False
                raise StopAsyncIteration

        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])

        async def on_event(event):
            callbacks.append(event)

        with patch("tollgate_mint_orchestrator.nostr_subscriber.websockets.connect", return_value=FakeWS()):
            await sub.start(on_event)

        assert len(callbacks) == 0

    @pytest.mark.asyncio
    async def test_handles_event_callback_exception(self):
        call_count = 0

        class FakeWS:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def send(self, msg):
                pass
            def __aiter__(self):
                return self
            async def __anext__(self):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return json.dumps(["EVENT", "sub1", {"kind": 38010}])
                sub._running = False
                raise StopAsyncIteration

        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])

        async def on_event(event):
            raise RuntimeError("test error")

        with patch("tollgate_mint_orchestrator.nostr_subscriber.websockets.connect", return_value=FakeWS()):
            await sub.start(on_event)

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_reconnects_on_connection_closed(self):
        import websockets.exceptions
        connect_count = 0

        def fake_connect(url):
            nonlocal connect_count
            connect_count += 1

            class FakeWS:
                async def __aenter__(self_inner):
                    if connect_count == 1:
                        raise websockets.exceptions.ConnectionClosed(None, None)
                    return self_inner
                async def __aexit__(self_inner, *args):
                    pass
                async def send(self_inner, msg):
                    pass
                def __aiter__(self_inner):
                    return self_inner
                async def __anext__(self_inner):
                    sub._running = False
                    raise StopAsyncIteration

            return FakeWS()

        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])
        on_event = AsyncMock()

        original_sleep = asyncio.sleep
        sleep_calls = []

        async def fast_sleep(delay):
            sleep_calls.append(delay)
            await original_sleep(0)

        with patch("tollgate_mint_orchestrator.nostr_subscriber.websockets.connect", side_effect=fake_connect):
            with patch("tollgate_mint_orchestrator.nostr_subscriber.asyncio.sleep", side_effect=fast_sleep):
                await sub.start(on_event)

        assert connect_count == 2
        assert len(sleep_calls) == 1
        assert sleep_calls[0] == 1

    @pytest.mark.asyncio
    async def test_reconnects_on_oserror(self):
        connect_count = 0

        def fake_connect(url):
            nonlocal connect_count
            connect_count += 1

            class FakeWS:
                async def __aenter__(self_inner):
                    if connect_count == 1:
                        raise OSError("connection refused")
                    return self_inner
                async def __aexit__(self_inner, *args):
                    pass
                async def send(self_inner, msg):
                    pass
                def __aiter__(self_inner):
                    return self_inner
                async def __anext__(self_inner):
                    sub._running = False
                    raise StopAsyncIteration

            return FakeWS()

        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])
        on_event = AsyncMock()

        original_sleep = asyncio.sleep

        async def fast_sleep(delay):
            await original_sleep(0)

        with patch("tollgate_mint_orchestrator.nostr_subscriber.websockets.connect", side_effect=fake_connect):
            with patch("tollgate_mint_orchestrator.nostr_subscriber.asyncio.sleep", side_effect=fast_sleep):
                await sub.start(on_event)

        assert connect_count == 2
        assert sub._backoff >= 1

    @pytest.mark.asyncio
    async def test_reconnects_on_unexpected_error(self):
        connect_count = 0

        def fake_connect(url):
            nonlocal connect_count
            connect_count += 1

            class FakeWS:
                async def __aenter__(self_inner):
                    if connect_count == 1:
                        raise RuntimeError("unexpected")
                    return self_inner
                async def __aexit__(self_inner, *args):
                    pass
                async def send(self_inner, msg):
                    pass
                def __aiter__(self_inner):
                    return self_inner
                async def __anext__(self_inner):
                    sub._running = False
                    raise StopAsyncIteration

            return FakeWS()

        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])
        on_event = AsyncMock()

        original_sleep = asyncio.sleep

        async def fast_sleep(delay):
            await original_sleep(0)

        with patch("tollgate_mint_orchestrator.nostr_subscriber.websockets.connect", side_effect=fake_connect):
            with patch("tollgate_mint_orchestrator.nostr_subscriber.asyncio.sleep", side_effect=fast_sleep):
                await sub.start(on_event)

        assert connect_count == 2

    @pytest.mark.asyncio
    async def test_backoff_doubles_and_caps(self):
        import websockets.exceptions
        backoffs = []

        def fake_connect(url):
            class FakeWS:
                async def __aenter__(self_inner):
                    raise websockets.exceptions.ConnectionClosed(None, None)
                async def __aexit__(self_inner, *args):
                    pass
            return FakeWS()

        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])
        on_event = AsyncMock()
        call_count = 0

        original_sleep = asyncio.sleep

        async def track_sleep(delay):
            nonlocal call_count
            backoffs.append(delay)
            call_count += 1
            if call_count >= 4:
                sub._running = False
            await original_sleep(0)

        with patch("tollgate_mint_orchestrator.nostr_subscriber.websockets.connect", side_effect=fake_connect):
            with patch("tollgate_mint_orchestrator.nostr_subscriber.asyncio.sleep", side_effect=track_sleep):
                await sub.start(on_event)

        assert backoffs == [1, 2, 4, 8]

    @pytest.mark.asyncio
    async def test_backoff_caps_at_max(self):
        import websockets.exceptions

        def fake_connect(url):
            class FakeWS:
                async def __aenter__(self_inner):
                    raise websockets.exceptions.ConnectionClosed(None, None)
                async def __aexit__(self_inner, *args):
                    pass
            return FakeWS()

        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])
        sub._backoff = 32
        on_event = AsyncMock()
        call_count = 0

        original_sleep = asyncio.sleep

        async def track_sleep(delay):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                sub._running = False
            await original_sleep(0)

        with patch("tollgate_mint_orchestrator.nostr_subscriber.websockets.connect", side_effect=fake_connect):
            with patch("tollgate_mint_orchestrator.nostr_subscriber.asyncio.sleep", side_effect=track_sleep):
                await sub.start(on_event)

        assert sub._backoff == 60


class TestNostrSubscriberStop:
    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])
        sub._running = True
        await sub.stop()
        assert sub._running is False

    @pytest.mark.asyncio
    async def test_stop_closes_websocket(self):
        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])
        mock_ws = AsyncMock()
        sub._ws = mock_ws
        sub._running = True
        await sub.stop()
        mock_ws.send.assert_called_once()
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent[0] == "CLOSE"
        assert sent[1] == sub.sub_id
        assert sub._ws is None

    @pytest.mark.asyncio
    async def test_stop_no_websocket(self):
        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])
        sub._running = True
        await sub.stop()
        assert sub._ws is None

    @pytest.mark.asyncio
    async def test_stop_handles_send_error(self):
        sub = NostrSubscriber("ws://localhost:7777", [{"kinds": [38010]}])
        mock_ws = AsyncMock()
        mock_ws.send.side_effect = RuntimeError("connection lost")
        sub._ws = mock_ws
        sub._running = True
        await sub.stop()
        assert sub._ws is None
