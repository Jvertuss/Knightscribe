import { useEffect, useRef } from "react";

interface VideoPlayerProps {
  title: string;
  videoUrl: string;
  seekTo?: { seconds: number } | null;
}

function VideoPlayer({ title, videoUrl, seekTo }: VideoPlayerProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // enablejsapi lets the page send commands to the YouTube player
  const src =
    videoUrl + (videoUrl.includes("?") ? "&" : "?") + "enablejsapi=1";

  useEffect(() => {
    if (!seekTo) return;
    const player = iframeRef.current?.contentWindow;
    player?.postMessage(
      JSON.stringify({
        event: "command",
        func: "seekTo",
        args: [seekTo.seconds, true],
      }),
      "*"
    );
    player?.postMessage(
      JSON.stringify({ event: "command", func: "playVideo", args: [] }),
      "*"
    );
  }, [seekTo]);

  return (
    <div className="video-player">
      <h2>{title}</h2>
      <iframe
        ref={iframeRef}
        width="100%"
        height="400"
        src={src}
        title={title}
        allow="autoplay; fullscreen"
        allowFullScreen
      />
    </div>
  );
}

export default VideoPlayer;