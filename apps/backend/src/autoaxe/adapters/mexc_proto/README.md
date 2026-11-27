# MEXC Futures Protobuf schema

Unmodified 69 upstream .proto files and LICENSE from the official public
https://github.com/mexcdevelop/websocket-future-proto/tree/033825833318b4bc3add4481997e9f76005c6483
(Apache-2.0). The complete descriptor preserves every ContractWrapper oneof arm,
not a guessed subset. `manifest.json` records SHA-256 for the exact bytes.

Regeneration (isolated build tool only, not a runtime dependency):
from this directory's `proto/` folder, with grpcio-tools==1.76.0 installed
in a separate environment (libprotoc 31.1), compile all *.proto paths in
ascending filename order:

    python -m grpc_tools.protoc -I . --include_imports --descriptor_set_out=../contract.desc <sorted *.proto files>

The runtime uses protobuf==7.36.2 and a fresh DescriptorPool, not generated
Python modules with ambiguous absolute imports. The checked descriptor is
41,481 bytes; SHA-256 f6ebc7533d5d533d4715b59771b9b48ac673bb18ee7e346f2dd740de6e95df77.
No live exchange payload was captured. Synthetic wire tests exercise the
official wrapper and tickerDetail arm, and reject incorrect channels/symbols.
