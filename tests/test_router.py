"""NotificationRouter — route 매칭·폴백 체인·default 검증."""

from aim.delivery.router import NotificationRouter


class ListNotifier:
    def __init__(self, name="list"):
        self.name = name
        self.sent = []

    def send(self, title, body_md):
        self.sent.append(title)
        return True


def test_route_direct_match():
    kr, default = ListNotifier("kr"), ListNotifier("default")
    router = NotificationRouter({"kr": [kr]}, [default])
    router.send("kr", "t", "b")
    assert kr.sent == ["t"] and default.sent == []


def test_unknown_route_falls_back_to_default():
    default = ListNotifier("default")
    router = NotificationRouter({}, [default])
    router.send("us", "t", "b")
    assert default.sent == ["t"]


def test_chain_prefers_specific_channel():
    surge, signals = ListNotifier("surge"), ListNotifier("signals")
    router = NotificationRouter({"surge": [surge], "signals": [signals]}, [ListNotifier()])
    router.send(("surge", "signals"), "t", "b")
    assert surge.sent == ["t"] and signals.sent == []


def test_chain_falls_through_to_signals():
    signals, default = ListNotifier("signals"), ListNotifier("default")
    router = NotificationRouter({"signals": [signals]}, [default])
    router.send(("surge", "signals"), "t", "b")  # surge 채널 미설정
    assert signals.sent == ["t"] and default.sent == []


def test_chain_all_missing_uses_default():
    default = ListNotifier("default")
    router = NotificationRouter({}, [default])
    router.send(("surge", "signals"), "t", "b")
    assert default.sent == ["t"]


def test_send_reports_failure():
    class FailNotifier:
        name = "fail"

        def send(self, title, body_md):
            return False

    router = NotificationRouter({}, [FailNotifier()])
    assert router.send("kr", "t", "b") is False
