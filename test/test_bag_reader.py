import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from piper_aio_ros2.bag_reader import open_reader


class FakeReader:
    def __init__(self, kind):
        self.kind = kind
        self.open_args = None

    def open(self, *args):
        self.open_args = args


def fake_rosbag2_py(compression_format, compression_mode):
    metadata = SimpleNamespace(
        compression_format=compression_format,
        compression_mode=compression_mode,
        storage_identifier="sqlite3",
    )
    return SimpleNamespace(
        Info=lambda: SimpleNamespace(read_metadata=lambda path, storage_id: metadata),
        SequentialReader=lambda: FakeReader("standard"),
        SequentialCompressionReader=lambda: FakeReader("compression"),
        StorageOptions=lambda **kwargs: SimpleNamespace(**kwargs),
        ConverterOptions=lambda **kwargs: SimpleNamespace(**kwargs),
    )


class BagReaderTest(unittest.TestCase):
    def assert_reader(self, compression_format, compression_mode, expected):
        module = fake_rosbag2_py(compression_format, compression_mode)
        with patch.dict(sys.modules, {"rosbag2_py": module}):
            reader = open_reader("/tmp/episode")
        self.assertEqual(reader.kind, expected)
        storage = reader.open_args[0]
        self.assertEqual(storage.uri, "/tmp/episode")
        self.assertEqual(storage.storage_id, "sqlite3")

    def test_uncompressed_uses_sequential_reader(self):
        self.assert_reader("", "", "standard")

    def test_file_and_message_compression_use_compression_reader(self):
        for mode in ("FILE", "MESSAGE"):
            with self.subTest(mode=mode):
                self.assert_reader("zstd", mode, "compression")


if __name__ == "__main__":
    unittest.main()
