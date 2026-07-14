"""验证独立快照发送脚本的发送周期。"""

from types import SimpleNamespace
import unittest
from unittest import mock

import send_frame


class SendFrameIntervalTestCase(unittest.TestCase):
    """校验发送完成与发送间隔等待的先后顺序。"""

    def test_interval_starts_after_send_finishes(self):
        """确认每次发送结束后才等待完整的命令行配置间隔。"""
        events = []
        arguments = SimpleNamespace(
            interval=1.25,
            once=False,
            ping_target="127.0.0.1",
            port=None,
        )
        parser = mock.Mock()
        parser.parse_args.return_value = arguments
        collector = mock.Mock()
        collector.collect.side_effect = [{"version": 1}, KeyboardInterrupt()]
        client = mock.Mock()
        client.send.side_effect = lambda snapshot: events.append(("发送完成", snapshot["version"]))

        with (
            mock.patch.object(send_frame, "create_argument_parser", return_value=parser),
            mock.patch.object(send_frame, "SystemInformationCollector", return_value=collector),
            mock.patch.object(send_frame, "PicoJsonClient", return_value=client),
            mock.patch.object(
                send_frame.time,
                "sleep",
                side_effect=lambda interval: events.append(("等待间隔", interval)),
            ),
            mock.patch("builtins.print"),
        ):
            send_frame.main()

        self.assertEqual([("发送完成", 1), ("等待间隔", 1.25)], events)
        client.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
