"""Live streaming: push generated videos to RTMP/RTMPS platforms, seamlessly.

`StreamManager` is the public entry point. It transcodes finished videos into
gapless MPEG-TS segments and hands them to an `RTMPBroadcaster` that keeps a
single encoder alive and fans out to every configured platform via the ffmpeg
`tee` muxer — so the stream never stops while new clips are produced.
"""

from app.streaming.manager import StreamManager
from app.streaming.base import StreamTarget, build_targets

__all__ = ["StreamManager", "StreamTarget", "build_targets"]
