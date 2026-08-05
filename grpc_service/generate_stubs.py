"""Generate Python gRPC stubs from chat.proto."""
from pathlib import Path
import re
import subprocess
import sys


def main() -> int:
    root = Path(__file__).resolve().parent
    proto_dir = root / "proto"
    proto_file = proto_dir / "chat.proto"

    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{proto_dir}",
        f"--python_out={root}",
        f"--grpc_python_out={root}",
        str(proto_file),
    ]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        return result.returncode

    # Fix relative import so `from grpc_service import chat_pb2` works in packages.
    grpc_file = root / "chat_pb2_grpc.py"
    text = grpc_file.read_text(encoding="utf-8")
    text = re.sub(
        r"^import chat_pb2 as (.+)$",
        r"from grpc_service import chat_pb2 as \1",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^import chat_pb2\b",
        "from grpc_service import chat_pb2",
        text,
        flags=re.MULTILINE,
    )
    # Drop brittle version hard-fail block so older/newer grpcio pairs still work.
    text = re.sub(
        r"GRPC_GENERATED_VERSION = .*\n.*?(?=class ChatServiceStub)",
        "\n",
        text,
        flags=re.DOTALL,
    )
    grpc_file.write_text(text, encoding="utf-8")
    print("Generated chat_pb2.py and chat_pb2_grpc.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
