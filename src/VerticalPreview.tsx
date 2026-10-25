import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import type { Crop, Video } from './types';

type Props = {
  video: Video | null; source: RefObject<HTMLVideoElement | null>; camera: Crop;
  split: number; fit: 'cover' | 'contain'; focus: number; time: number;
};

export default function VerticalPreview({ video, source, camera, split, fit, focus, time }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const poster = useRef<HTMLImageElement | null>(null);
  useEffect(() => {
    const img = new Image();
    img.src = video?.poster || '/demo-poster.jpg';
    poster.current = img;
  }, [video?.poster]);
  useEffect(() => {
    let frame = 0;
    const canvas = ref.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    const draw = () => {
      const v = source.current;
      const readyPoster = poster.current?.complete && poster.current.naturalWidth ? poster.current : null;
      const readyVideo = v && v.readyState >= 2 && v.videoWidth > 0 ? v : null;
      const image: CanvasImageSource | null = readyVideo && (readyVideo.currentTime > 0 || !readyVideo.paused) ? readyVideo : readyPoster || readyVideo;
      ctx.fillStyle = '#0b0d12'; ctx.fillRect(0, 0, 540, 960);
      if (image) {
        const w = image instanceof HTMLVideoElement ? image.videoWidth : (image as HTMLImageElement).naturalWidth;
        const h = image instanceof HTMLVideoElement ? image.videoHeight : (image as HTMLImageElement).naturalHeight;
        const topH = Math.floor(960 * split / 2) * 2;
        const region = (sx: number, sy: number, sw: number, sh: number, dy: number, dh: number, mode: 'cover' | 'contain', fx = .5) => {
          const factor = mode === 'cover' ? Math.max(540 / sw, dh / sh) : Math.min(540 / sw, dh / sh);
          const dw = sw * factor, height = sh * factor;
          ctx.save(); ctx.beginPath(); ctx.rect(0, dy, 540, dh); ctx.clip();
          ctx.drawImage(image, sx, sy, sw, sh, (540 - dw) * fx, dy + (dh - height) / 2, dw, height); ctx.restore();
        };
        region(camera.x * w, camera.y * h, camera.width * w, camera.height * h, 0, topH, 'cover');
        region(0, 0, w, h, topH, 960 - topH, fit, fit === 'contain' ? .5 : focus);
      }
      if (v && !v.paused && !v.ended) frame = requestAnimationFrame(draw);
    };
    const redraw = () => { cancelAnimationFrame(frame); draw(); };
    const currentSource = source.current;
    const currentPoster = poster.current;
    const events = ['loadeddata', 'seeked', 'play', 'pause', 'timeupdate', 'error'];
    events.forEach(event => currentSource?.addEventListener(event, redraw));
    currentPoster?.addEventListener('load', redraw);
    draw();
    return () => {
      cancelAnimationFrame(frame);
      events.forEach(event => currentSource?.removeEventListener(event, redraw));
      currentPoster?.removeEventListener('load', redraw);
    };
  }, [video, source, camera, split, fit, focus, time]);
  return <canvas ref={ref} width="540" height="960" aria-label="Kamera üstte, içerik altta dikey video önizlemesi" />;
}
