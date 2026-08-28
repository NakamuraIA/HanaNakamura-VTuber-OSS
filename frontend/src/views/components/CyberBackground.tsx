import { useEffect, useRef } from 'react';

export function CyberBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const mouseRef = useRef<{ x: number; y: number; active: boolean }>({ x: -9999, y: -9999, active: false });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    const particles: { x: number; y: number; size: number; speedX: number; speedY: number; opacity: number }[] = [];

    const resizeCanvas = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };

    window.addEventListener('resize', resizeCanvas);
    resizeCanvas();

    // Mouse interaction: particles drift away from the cursor (soft repulsion).
    const handleMouseMove = (e: MouseEvent) => {
      mouseRef.current = { x: e.clientX, y: e.clientY, active: true };
    };
    const handleMouseLeave = () => {
      mouseRef.current.active = false;
    };
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseleave', handleMouseLeave);

    // Sparse neutral dust keeps depth without returning to a sci-fi particle field.
    for (let i = 0; i < 42; i++) {
      particles.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        size: Math.random() * 1.3 + 0.35,
        speedX: (Math.random() - 0.5) * 0.22,
        speedY: (Math.random() - 0.5) * 0.18 - 0.06,
        opacity: Math.random() * 0.16 + 0.035,
      });
    }

    const MOUSE_RADIUS = 130;

    const draw = () => {
      const dustColor = '#d8dbe0';

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      ctx.shadowBlur = 0;
      ctx.shadowColor = dustColor;
      ctx.fillStyle = dustColor;

      const mouse = mouseRef.current;

      particles.forEach((p) => {
        p.x += p.speedX;
        p.y += p.speedY;

        // Soft repulsion from the cursor so the field reacts as you move the mouse.
        if (mouse.active) {
          const dx = p.x - mouse.x;
          const dy = p.y - mouse.y;
          const dist = Math.hypot(dx, dy);
          if (dist < MOUSE_RADIUS && dist > 0.01) {
            const force = (1 - dist / MOUSE_RADIUS) * 1.6;
            p.x += (dx / dist) * force;
            p.y += (dy / dist) * force;
          }
        }

        // Twinkle.
        p.opacity += (Math.random() - 0.5) * 0.02;
        p.opacity = Math.max(0.025, Math.min(0.22, p.opacity));

        // Wrap around the edges.
        if (p.y < -10) p.y = canvas.height + 10;
        if (p.y > canvas.height + 10) p.y = -10;
        if (p.x < -10) p.x = canvas.width + 10;
        if (p.x > canvas.width + 10) p.x = -10;

        ctx.globalAlpha = p.opacity;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fill();
      });

      ctx.globalAlpha = 1.0;
      ctx.shadowBlur = 0;
    };

    const renderLoop = () => {
      draw();
      animationFrameId = requestAnimationFrame(renderLoop);
    };

    animationFrameId = requestAnimationFrame(renderLoop);

    return () => {
      window.removeEventListener('resize', resizeCanvas);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseleave', handleMouseLeave);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return (
    <div className="fixed top-0 left-0 w-full h-full pointer-events-none z-[-1] overflow-hidden bg-[var(--bg-dark)]">
      {/* Fundo chapado (estilo ChatGPT): preto liso, sem brilhos de canto nem
          vinheta. Só a poeira neutra bem sutil pra não ficar morto. */}
      <canvas ref={canvasRef} className="absolute inset-0" />
    </div>
  );
}
