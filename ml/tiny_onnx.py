"""Tiny ONNX Identity graph for CUDA provider checks.

The bytes are a 108-byte Identity model (float32 [1, 4]).
They are a test graph, not pose weights.
Never commit .onnx weight files.
"""

from __future__ import annotations

# Produced with onnx.helper (Identity, opset 21). Not a trained model.
TINY_IDENTITY_HEX = (
    "080a1213636c696d62696e672d636f6163682d746573743a4f0a140a0158120159"
    "1a02696422084964656e74697479120d74696e795f6964656e746974795a130a01"
    "58120e0a0c080112080a0208010a02080462130a0159120e0a0c080112080a0208"
    "010a02080442021015"
)


def tiny_identity_bytes() -> bytes:
    """Return the embedded Identity model."""
    return bytes.fromhex(TINY_IDENTITY_HEX)
