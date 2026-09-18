"""Local deterministic model protocol fixture, never a production model."""

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@contextmanager
def open_model_endpoint():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(
                {
                    "body": body,
                    "authorization": self.headers.get("Authorization"),
                    "path": self.path,
                }
            )
            if body["messages"][-1].get("content", "").startswith("慢"):
                time.sleep(2)
            if body["messages"][-1]["role"] == "tool":
                deltas = [{"role": "assistant", "content": "结果是 "}, {"content": "5"}]
                finish = "stop"
            else:
                deltas = [
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_add",
                                "type": "function",
                                "function": {
                                    "name": "calculate",
                                    "arguments": '{"operation":"add",',
                                },
                            }
                        ],
                    },
                    {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": '"a":2,"b":3}'}}
                        ]
                    },
                ]
                finish = "tool_calls"
            if not body.get("stream", False):
                if finish == "tool_calls":
                    message = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_add",
                                "type": "function",
                                "function": {
                                    "name": "calculate",
                                    "arguments": '{"operation":"add","a":2,"b":3}',
                                },
                            }
                        ],
                    }
                else:
                    message = {"role": "assistant", "content": "结果是 5"}
                payload = json.dumps(
                    {
                        "id": "chatcmpl-local",
                        "object": "chat.completion",
                        "created": 1,
                        "model": body["model"],
                        "choices": [
                            {"index": 0, "message": message, "finish_reason": finish}
                        ],
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 3,
                            "total_tokens": 13,
                        },
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except OSError:
                    pass
                return
            chunks = [
                {
                    "id": "chatcmpl-local",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": body["model"],
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                }
                for delta in deltas
            ]
            chunks.append(
                {
                    "id": "chatcmpl-local",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": body["model"],
                    "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                }
            )
            payload = (
                "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
                + "data: [DONE]\n\n"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload.encode())))
            self.end_headers()
            try:
                self.wfile.write(payload.encode())
            except OSError:
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
