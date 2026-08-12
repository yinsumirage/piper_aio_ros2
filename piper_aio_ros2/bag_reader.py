"""Small rosbag2 reader helpers; ROS imports stay out of pure-function tests."""

from collections import Counter

from .sync import message_time_ns


def open_reader(bag_path):
    import rosbag2_py

    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag_path), storage_id=""),
        rosbag2_py.ConverterOptions(input_serialization_format="", output_serialization_format=""),
    )
    return reader


def index_bag(bag_path, streams):
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    reader = open_reader(bag_path)
    bag_types = {topic.name: topic.type for topic in reader.get_all_topics_and_types()}
    by_topic = {spec["topic"]: name for name, spec in streams.items()}
    message_types = {
        topic: get_message(bag_types[topic]) for topic in by_topic if topic in bag_types
    }
    entries = {name: [] for name in streams}
    receive_counts = Counter()
    while reader.has_next():
        topic, serialized, receive_ns = reader.read_next()
        if topic not in by_topic:
            continue
        ordinal = receive_counts[topic]
        receive_counts[topic] += 1
        message = deserialize_message(serialized, message_types[topic])
        source_ns, timestamp_source = message_time_ns(message, receive_ns)
        name = by_topic[topic]
        entries[name].append(
            {
                "source_ns": source_ns,
                "receive_ns": int(receive_ns),
                "timestamp_source": timestamp_source,
                "ordinal": ordinal,
                "message": None if streams[name]["kind"] == "rgb" else message,
            }
        )
    for stream_entries in entries.values():
        stream_entries.sort(key=lambda entry: (entry["source_ns"], entry["receive_ns"]))
    return bag_types, entries


def stream_report(streams, bag_types, entries):
    report = {}
    for name, spec in streams.items():
        stream_entries = entries[name]
        times = [entry["source_ns"] for entry in stream_entries]
        sources = Counter(entry["timestamp_source"] for entry in stream_entries)
        duration_ns = times[-1] - times[0] if len(times) > 1 else 0
        report[name] = {
            "topic": spec["topic"],
            "expected_type": spec["type"],
            "bag_type": bag_types.get(spec["topic"]),
            "count": len(times),
            "rate_hz": (len(times) - 1) * 1e9 / duration_ns if duration_ns > 0 else None,
            "first_ns": times[0] if times else None,
            "last_ns": times[-1] if times else None,
            "timestamp_source": dict(sorted(sources.items())),
        }
    return report
