import { useEffect, useRef } from "react";

const LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
const CELL_W = 15; // horizontal spacing between letters, in pixels
const CELL_H = 26; // vertical spacing between rows

function randomLetter() {
  return LETTERS[Math.floor(Math.random() * LETTERS.length)];
}

function LetterBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    let cols = 0;
    let rows = 0;
    let letters: string[] = [];
    let glow: number[] = []; // 1 = just typed (bright gold), fades to 0
    let typists: { row: number; col: number }[] = [];

    const setup = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      cols = Math.ceil(canvas.width / CELL_W);
      rows = Math.ceil(canvas.height / CELL_H);
      letters = Array.from({ length: cols * rows }, randomLetter);
      glow = new Array(cols * rows).fill(0);
      typists = Array.from({ length: Math.max(3, Math.round(rows / 6)) }, () => ({
        row: Math.floor(Math.random() * rows),
        col: Math.floor(Math.random() * cols),
      }));
    };

    const step = () => {
      // random letters flicker and change
      for (let i = 0; i < 25; i++) {
        const idx = Math.floor(Math.random() * letters.length);
        letters[idx] = randomLetter();
        glow[idx] = 0.6;
      }
      // typists move along a row, typing a letter at each step
      for (const t of typists) {
        const idx = t.row * cols + t.col;
        letters[idx] = randomLetter();
        glow[idx] = 1;
        t.col += 1;
        if (t.col >= cols) {
          t.col = 0;
          t.row = Math.floor(Math.random() * rows);
        }
      }
    };

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.font = '18px "Special Elite", "Courier New", monospace';
      ctx.textBaseline = "top";
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const i = r * cols + c;
          const g = glow[i];
          ctx.fillStyle =
            g > 0.05
              ? `rgba(255, 201, 4, ${0.2 + g * 0.8})`
              : "rgba(255, 255, 255, 0.2)";
          ctx.fillText(letters[i], c * CELL_W, r * CELL_H);
          glow[i] = g * 0.9; // fade out
        }
      }
    };

    setup();
    draw();

    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    let timer: number | undefined;
    if (!reduceMotion) {
      timer = window.setInterval(() => {
        step();
        draw();
      }, 110);
    }

    const onResize = () => {
      setup();
      draw();
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.clearInterval(timer);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  return (
    <div className="letter-bg" aria-hidden="true">
      <canvas ref={canvasRef} />
    </div>
  );
}

export default LetterBackground;