"""Tests for the event bus.

The bus is module-level state, so every test cleans up after itself — a leaked
subscriber would otherwise fire during unrelated tests.
"""

import logging

import pytest

from supervisor.events import Event, EventType, emit, subscribe, unsubscribe


@pytest.fixture
def collector():
    """Subscribe a recorder for the duration of one test."""
    received: list[Event] = []
    subscribe(received.append)
    yield received
    unsubscribe(received.append)


class TestDelivery:
    def test_emit_delivers_type_and_payload(self):
        received: list[Event] = []
        subscribe(received.append)
        try:
            emit(EventType.STATUS, text="hello", count=3)
        finally:
            unsubscribe(received.append)

        assert len(received) == 1
        assert received[0].type is EventType.STATUS
        assert received[0].data == {"text": "hello", "count": 3}

    def test_emit_with_no_payload_gives_empty_data(self):
        received: list[Event] = []
        subscribe(received.append)
        try:
            emit(EventType.INTERRUPT)
        finally:
            unsubscribe(received.append)

        assert received[0].data == {}

    def test_every_subscriber_gets_the_event(self):
        a: list[Event] = []
        b: list[Event] = []
        subscribe(a.append)
        subscribe(b.append)
        try:
            emit(EventType.SUMMARY)
        finally:
            unsubscribe(a.append)
            unsubscribe(b.append)

        assert len(a) == len(b) == 1


class TestUnsubscribe:
    def test_unsubscribed_callback_stops_receiving(self):
        received: list[Event] = []
        subscribe(received.append)
        unsubscribe(received.append)
        emit(EventType.STATUS, text="ignored")
        assert received == []

    def test_unsubscribing_an_unknown_callback_is_a_no_op(self):
        unsubscribe(lambda event: None)  # must not raise


class TestSubscriberFailure:
    def test_one_broken_subscriber_does_not_starve_the_others(self, caplog):
        def explode(event: Event) -> None:
            raise RuntimeError("subscriber is broken")

        received: list[Event] = []
        subscribe(explode)
        subscribe(received.append)
        try:
            with caplog.at_level(logging.ERROR, logger="supervisor.events"):
                emit(EventType.STATUS, text="still delivered")
        finally:
            unsubscribe(explode)
            unsubscribe(received.append)

        assert len(received) == 1, "a raising subscriber must not block later ones"
        assert "subscriber is broken" in caplog.text


def test_fixture_based_collection(collector):
    emit(EventType.QUEUE_UPDATE, count=2)
    assert collector[-1].data["count"] == 2
