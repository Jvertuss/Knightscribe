import { useEffect, useRef, useState } from "react";
import LiveAudioBar from "./LiveAudioBar";

interface VideoPlayerProps {
  title: string;
  videoUrl: string;
  seekTo?: { seconds: number } | null;
}

const MJPEG_PREFIX = "mjpeg:";

const isYouTube = (url: string) =>
  /youtube\.com|youtube-nocookie\.com|youtu\.be/i.test(url);

// The Pi serves its live sound next to the camera: .../video -> .../audio
function piAudioUrl(videoUrl: string): string | null {
  try {
    return new URL("/audio", videoUrl).href;
  } catch {
    return null;
  }
}

// Live camera from the Raspberry Pi (MJPEG over HTTP)
function MjpegView({ url, title }: { url: string; title: string }) {
  const [failed, setFailed] = useState(false);
  const audioUrl = piAudioUrl(url);

  if (failed) {
    return (
      <div className="video-empty">
        <strong>Can't reach the camera</strong>
        <span>
          Make sure this computer is on the same network as the Raspberry Pi.
        </span>
      </div>
    );
  }

  return (
    <>
      <div className="live-frame">
        <img src={url} alt={`${title} live camera`} onError={() => setFailed(true)} />
        <span className="live-badge">LIVE</span>
      </div>
      {audioUrl && <LiveAudioBar src={audioUrl} />}
    </>
  );
}

function VideoPlayer({ title, videoUrl, seekTo }: VideoPlayerProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  const hasVideo = videoUrl.trim() !== "";
  const isMjpeg = videoUrl.startsWith(MJPEG_PREFIX);
  const mjpegUrl = isMjpeg ? videoUrl.slice(MJPEG_PREFIX.length) : "";
  const youtube = hasVideo && !isMjpeg && isYouTube(videoUrl);
  const plainVideo = hasVideo && !isMjpeg && !youtube;

  // enablejsapi lets the page send commands to the YouTube player
  const youtubeSrc = youtube
    ? videoUrl + (videoUrl.includes("?") ? "&" : "?") + "enablejsapi=1"
    : "";

  useEffect(() => {
    if (!seekTo || isMjpeg) return; // a live camera can't be seeked

    if (youtube) {
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
    } else if (videoRef.current) {
      const video = videoRef.current;
      const jump = () => {
        video.currentTime = seekTo.seconds;
        video.play().catch(() => {
          // the browser may block autoplay, the user can press play
        });
      };
      // a jump requested before the video has loaded waits until it knows its length
      if (video.readyState >= 1) jump();
      else video.addEventListener("loadedmetadata", jump, { once: true });
    }
    // only react to a new seek request
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seekTo]);

  return (
    <div className="video-player">
      <h2>{title}</h2>

      {!hasVideo && (
        <div className="video-empty">
          <strong>No video yet</strong>
          <span>The camera or recording will appear here once it starts.</span>
        </div>
      )}

      {isMjpeg && <MjpegView key={mjpegUrl} url={mjpegUrl} title={title} />}

      {youtube && (
        <iframe
          ref={iframeRef}
          width="100%"
          height="400"
          src={youtubeSrc}
          title={title}
          allow="autoplay; fullscreen"
          allowFullScreen
        />
      )}

      {plainVideo && (
        <video
          ref={videoRef}
          src={videoUrl}
          controls
          playsInline
          preload="metadata"
        />
      )}
    </div>
  );
}

export default VideoPlayer;